import os
from enum import Enum
from logging import FileHandler, getLogger
from math import ceil, log
from time import time

from ryu.lib import hub

#codici ANSI utili per colorare le stampe nel terminale
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

#stato di allarme del flusso 
class AlarmState(Enum):

    ALLARM_ON = 1    #il flusso va bloccato
    ALLARM_OFF = -1  #allarme spento


class Mitigation(object):
    """
    Responsabilità:
    - mantenere un contatore di sospetto per ogni flow;
    - accendere l'allarme solo dopo più rilevazioni consecutive;
    - installare una regola OpenFlow di DROP a priorità maggiore del forwarding;
    - rimuovere automaticamente la regola dopo un tempo di blocco;
    - aumentare progressivamente la durata del blocco per flow recidivi.
    """

    DROP_PRIORITY = 10 #la priorità della regola di drop deve essere alta

    def __init__(self):
        os.makedirs("log", exist_ok=True)

        self.logger = getLogger(self.__class__.__name__)
        self._setup_file_logger("log/Mitigation.txt")

        # Numero di rilevazioni sospette necessarie prima di bloccare.
        self.threshold = 3

        # Parametri del blocco temporaneo esponenziale: il primo blocco dura 4s, poi 16s fino a un massimo di 30
        self.base_time = 4
        self.max_time = 30
        self.max_counter = ceil(log(self.max_time, self.base_time))

        # Struttura:
        # {
        #   dpid: {
        #       flow_id: [alarm_counter, AllarmState, total_blocks]
        #   }
        # }
        #flow_id comprende in_port, MAC sorgente e MAC destinazione
        self.alarm_flow = {}

        #serve a evitare doppie installazioni della stessa drop rule.
        self.locked_flows = set()

        #salva il tempo di avvio della mitigation
        self.start_time = time()

    def _setup_file_logger(self, path):
        """
        Aggiunge un FileHandler evitando duplicati se Ryu ricarica l'app.
        """
        log_path = os.path.abspath(path)

        for handler in self.logger.handlers:
            if isinstance(handler, FileHandler):
                if os.path.abspath(handler.baseFilename) == log_path:
                    return

        self.logger.addHandler(FileHandler(log_path))

    #inizializza lo stato di allarme per un flusso, se non esiste già
    def create_flow_alarm(self, dpid, flow_id):

        if dpid not in self.alarm_flow:
            self.alarm_flow[dpid] = {}

        if flow_id not in self.alarm_flow[dpid]:
            self.alarm_flow[dpid][flow_id] = [
                0,                       # alarm_counter
                AllarmState.ALLARM_OFF,  # stato allarme
                0,                       # numero totale di blocchi
            ]
            self.logger.debug("Created alarm state for dpid=%s flow=%s", dpid, flow_id)

        return self.alarm_flow[dpid][flow_id]

    #incrementa il contatore di sospetto del flusso, se ha già ricevuto 3 avvertimenti viene attivato lo stato di allarme
    def increment_flow_alarm(self, dpid, flow_id):

        self.create_flow_alarm(dpid, flow_id)

        alarm_state = self.alarm_flow[dpid][flow_id]

        if alarm_state[0] < self.threshold:
            alarm_state[0] += 1

        if alarm_state[0] >= self.threshold:
            alarm_state[0] = self.threshold
            alarm_state[1] = AllarmState.ALLARM_ON

            self.logger.warning(
                RED + "[%.2f] Alarm ON for dpid=%s flow=%s counter=%d/%d" + RESET,
                time() - self.start_time,
                dpid,
                flow_id,
                alarm_state[0],
                self.threshold,
            )
        #stampa a video il flusso sospetto (se non ha ancora raggiunto la soglia di 3 rilevazioni sospette)    
        else:
            self.logger.info(
                YELLOW + "[%.2f] Suspicious flow on dpid=%s flow=%s counter=%d/%d" + RESET,
                time() - self.start_time,
                dpid,
                flow_id,
                alarm_state[0],
                self.threshold,
            )

        return list(alarm_state)

    #decrementa il contatore di sospetto, non gestisce lo sblocco dallo stato di allarme
    def decrement_flow_alarm(self, dpid, flow_id):

        if dpid not in self.alarm_flow:
            return None

        if flow_id not in self.alarm_flow[dpid]:
            return None

        alarm_state = self.alarm_flow[dpid][flow_id]

        if alarm_state[0] > 0:
            alarm_state[0] -= 1

        self.logger.debug(
            GREEN + "[%.2f] Flow normal on dpid=%s flow=%s counter=%d/%d" + RESET,
            time() - self.start_time,
            dpid,
            flow_id,
            alarm_state[0],
            self.threshold,
        )

        return list(alarm_state)

    #resetta il numero di blocchi totali per un flusso
    def reset_counter_alarm(self, flow_id, dpid):
 
        if dpid in self.alarm_flow and flow_id in self.alarm_flow[dpid]:
            self.alarm_flow[dpid][flow_id][2] = 0

    #costruisce il match OpenFlow con cui poi dopo andremo a bloccare lo specifico flusso e non l'intera sorgente
    def _build_flow_match(self, datapath, flow_id):

        parser = datapath.ofproto_parser

        if len(flow_id) < 3:
            raise ValueError("flow_id must be (in_port, eth_src, eth_dst)")

        return parser.OFPMatch(
            in_port=flow_id[0],
            eth_src=flow_id[1],
            eth_dst=flow_id[2],
        )

    #calcola il tempo di blocco con backoff esponenziale
    def _compute_wait_time(self, dpid, flow_id):

        #prendo lo stato del flusso e incremento il numero di blocchi
        alarm_state = self.alarm_flow[dpid][flow_id]

        alarm_state[2] += 1
        total_blocks = alarm_state[2]

        #saturo il contatore dei blocchi se sono arrivato al massimo 
        if total_blocks >= self.max_counter:
            alarm_state[2] = self.max_counter
            return self.max_time

        return self.base_time ** total_blocks


    #regola di drop per il flusso installata nello switch
    def lock_flow(self, datapath, flow_id):

        dpid = datapath.id
        self.create_flow_alarm(dpid, flow_id)

        #creo una chiave unica per il blocco e controllo se il flusso era già bloccato
        lock_key = (dpid, flow_id)
        if lock_key in self.locked_flows:
            self.logger.debug("Flow already locked: dpid=%s flow=%s", dpid, flow_id)
            return                                                                      #se il flusso è già bloccato, esco senza fare niente

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        try:
            match = self._build_flow_match(datapath, flow_id)
        except ValueError as exc:
            self.logger.warning("Cannot lock flow %s on dpid=%s: %s", flow_id, dpid, exc)
            return

        #calcolo quanto deve durare il blocco
        wait = self._compute_wait_time(dpid, flow_id)

        #una flow entry senza istruzioni corrisponde all'istruzione drop
        instructions = []

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_ADD,
            priority=self.DROP_PRIORITY,
            match=match,
            instructions=instructions,
            idle_timeout=0,                      #non rimuove la regola per inattività
            hard_timeout=int(wait) + 2,          #se il flusso non viene sbloccato manualmente, sarà sbloccato al termine di questo timeout
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            flags=ofproto.OFPFF_SEND_FLOW_REM,
        )

        datapath.send_msg(flow_mod)      #invio la regola di drop con priorità DROP_PRIORITY allo switch 
        self.locked_flows.add(lock_key)

        self.logger.warning(
            RED + "[%.2f] Blocked flow on dpid=%s flow=%s for %s seconds" + RESET,
            time() - self.start_time,
            dpid,
            flow_id,
            wait,
        )

        #thread che sblocca il flusso dopo "wait" secondi
        hub.spawn(self.unlock_flow, datapath, flow_id, wait) 


    #rimozione della regola di drop e reset dello stato di allarme
    def unlock_flow(self, datapath, flow_id, wait):
  
        hub.sleep(wait)

        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        try:
            match = self._build_flow_match(datapath, flow_id)   #ricostruisco lo stesso match usato per bloccare il flusso 
        except ValueError as exc:
            self.logger.warning("Cannot unlock flow %s on dpid=%s: %s", flow_id, dpid, exc)
            return

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE_STRICT,    #comando per eliminare una regola
            priority=self.DROP_PRIORITY,
            match=match,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
        )

        datapath.send_msg(flow_mod)      #invio allo switch il comando di eliminazione della regola

        lock_key = (dpid, flow_id)
        self.locked_flows.discard(lock_key)  #rimozione del flusso dalla lista dei flussi bloccati 

        if dpid in self.alarm_flow and flow_id in self.alarm_flow[dpid]:
            self.alarm_flow[dpid][flow_id][1] = AllarmState.ALLARM_OFF   #spengo l'allarme

            # Dopo lo sblocco lasciamo il counter appena sotto soglia:
            # se il flow torna subito sospetto, basta un'altra rilevazione per ribloccarlo.
            if self.alarm_flow[dpid][flow_id][0] >= self.threshold:
                self.alarm_flow[dpid][flow_id][0] = self.threshold - 1

        self.logger.info(
            GREEN + "[%.2f] Unlocked flow on dpid=%s flow=%s" + RESET,
            time() - self.start_time,
            dpid,
            flow_id,
        )
