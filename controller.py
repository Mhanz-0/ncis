import json
import os
import time
from logging import FileHandler

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3

from components.detection import Detection, FlowState, ListState
from components.mitigation import Mitigation, AlarmState
from components.monitoring import Monitoring
from components.policy import Policy
from components.statistics import Statistics, StatisticsState

#codici ANSI utili per colorare le stampe nel terminale
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

MONITOR_INTERVAL = 1.0
STAT_TO_AGGREGATE = "flow_rate"

#la detection mode deve essere specificata da terminale prima dell'avvio del controller, altrimenti sarà settata di default a "percentile"
DETECTION_MODE = os.environ.get("DETECTION_MODE", "percentile")

#controller principale per monitoring, detection e mitigation degli attacchi
#NON gestisce la parte di routing che è demandata al controller simple_switch13
class MainController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(MainController, self).__init__(*args, **kwargs)

        self._ensure_runtime_files()
        self._setup_file_logger()
         
        #modularizzazione del controller in componenti 
        self.monitoring = Monitoring(self.logger)
        self.mitigation = Mitigation()
        self.statistics = Statistics(self.logger)
        self.detection = Detection(self.logger, mode = DETECTION_MODE)
        self.policy = Policy(self.logger)

        #salva i datapath degli switch connessi al controller
        self.datapaths = {}
        
        #salva l'ultimo timestamp di richiesta stats per ogni switch
        self.last_request_time = {}

        #stato del round corrente di monitoraggio.
        self.dpids_received = set()
        self.received_non_empty_stats = False
        
        self.monitor_thread = hub.spawn(self._monitor)
        self.policy_thread = hub.spawn(self.policy.update_lists)

        self.logger.info("MainController started")
    
    #crea le cartelle e i file necessari alle componenti, se non esistono ancora 
    def _ensure_runtime_files(self):

        os.makedirs("log", exist_ok=True)
        os.makedirs("jsonFile", exist_ok=True)

        default_json_files = {
            "jsonFile/statistics.json": {},
            "jsonFile/aggregatedStats.json": {},
            "jsonFile/blackList.json": {},
            "jsonFile/whiteList.json": {},
        }

        for path, default_content in default_json_files.items():
            if not os.path.exists(path):
                with open(path, "w") as f:
                    json.dump(default_content, f, indent=2)

    #aggiunge un file handler senza duplicarlo se ryu ricarica l'app
    def _setup_file_logger(self):
        
        log_path = os.path.abspath("log/MainControllerLog.txt")

        for handler in self.logger.handlers:
            if isinstance(handler, FileHandler):
                if os.path.abspath(handler.baseFilename) == log_path:
                    return
                
        self.logger.addHandler(FileHandler(log_path))        


    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    #handler per la connessione e disconnessione degli switch
    def _state_change_handler(self, ev):
        self.monitoring.state_change_handler(ev,self.datapaths)

    #thread periodico che invia richieste di statistiche a tutti gli switch connessi al controller ogni MONITOR_INTERVAL secondi
    def _monitor(self):
 
        while True:
            if not self.datapaths:
                self.logger.info("No datapath registered yet")
                hub.sleep(MONITOR_INTERVAL)
                continue

            self.logger.info("\n#########################################################")
            self.logger.info("Sending flow stats requests to %d datapath(s)", len(self.datapaths))

            for dp in list(self.datapaths.values()):
                self.monitoring._request_stats(dp)

            hub.sleep(MONITOR_INTERVAL)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        
        """
        handler per la ricezione delle statistiche dei flussi dagli switch

        pipeline:
        1. filtro solo flow priority=1, cioè quelli creati dal simpleSwitch13;
        2. calcolo flow_rate e packet_diff tramite Statistics;
        3. quando tutti gli switch hanno risposto, calcolo soglia adattiva;
        4. faccio detection;
        5. se necessario chiamo Mitigation.

        """
        #salvo il datapath e il dpid dello switch che ha inviato le statistiche
        datapath = ev.msg.datapath
        dpid = datapath.id
        body = ev.msg.body 

        # calcolo il tempo trascorso dall'ultima richiesta di statistiche per questo switch
        now = time.perf_counter()
        previous_request = self.last_request_time.get(dpid)
        if previous_request is None:
            time_diff = MONITOR_INTERVAL
        else:
            time_diff = max(now - previous_request, 1e-6)
        
        self.last_request_time[dpid] = now

        #estraggo solo i flussi di forwarding (a priorità 1)
        low_priority_flows = self._extract_forwarding_flows(body)

        #aggiorno le statistiche dei flussi tramite la componente statistics
        result = self.statistics.setup_computations(
            time_diff=time_diff,
            datapath_id=dpid,
            raw_flow_stats=low_priority_flows,
        )

        #se almeno uno switch ha inviato statistiche non vuote, aggiorno le statistiche aggregate e faccio detection/mitigation
        if result == StatisticsState.SETUP_SUCCESS:
            self.received_non_empty_stats = True
            for raw_flow in low_priority_flows:
                self.statistics.compute_stat(raw_flow)

        #salvo il dpid dello switch che ha inviato le statistiche per sapere quando tutti gli switch hanno risposto
        self.dpids_received.add(dpid)
        self.logger.info(
            "Datapaths that have sent stats: %d/%d",
            len(self.dpids_received),
            len(self.datapaths),
        )

        if self._all_datapaths_replied():
            self._process_detection_round()
            self._reset_round_state()

    def _extract_forwarding_flows(self, body):
        """
        prende solo i flussi installati dal simple_switch13

        Nel nostro schema:
        - priority=0 è la table-miss;
        - priority=1 è forwarding normale;
        - priority>=2 sarà mitigation.
        """
        flows = []

        #
        for flow in body:
            if flow.priority != 1: #se il flusso non ha priorità 1 lo ignoro
                continue

            if "in_port" not in flow.match: #se il flusso non ha in_port lo ignoro
                continue

            if flow.match.get("eth_src") is None or flow.match.get("eth_dst") is None: #se il flusso non ha MAC sorgente o destinazione lo ignoro
                continue
 
            flows.append(flow) #salvo i flussi validi

        #restituisco i flussi ordinati per in_port, MAC sorgente e MAC destinazione 
        return sorted(
            flows,
            key=lambda flow: (
                flow.match["in_port"],
                flow.match.get("eth_src"),
                flow.match.get("eth_dst"),
            ),
        )

    #funzione di utilità per verificare se tutti gli switch hanno inviato le statistiche
    def _all_datapaths_replied(self):
        if not self.datapaths:
            return False
        return self.dpids_received.issuperset(set(self.datapaths.keys()))

    #funzione di utilità per resettare lo stato del round corrente
    def _reset_round_state(self):
        self.dpids_received.clear()
        self.received_non_empty_stats = False

    def _set_adaptive_threshold(self, aggregated_stats):
        """
        Imposta i parametri della soglia adattiva in base alla modalità scelta.
        La soglia vera e propria viene poi calcolata dentro Detection._compute_threshold_value().
        """

        mode = self.detection.mode

        if mode == "percentile":
            percentile = aggregated_stats["percentile"]
            iqr = aggregated_stats["iqr"]

            self.detection.setThreshold(percentile, iqr)

            self.logger.info(
                "Adaptive threshold mode=percentile: flow_rate > percentile75 + 1.5 * IQR = %.3f + 1.5 * %.3f",
                percentile,
                iqr,
            )
            return

        if mode == "average&std_dev":
            average = aggregated_stats["average"]
            std_dev = aggregated_stats["std_dev"]

            self.detection.setThreshold(average, std_dev)

            self.logger.info(
                "Adaptive threshold mode=average&std_dev: flow_rate > average + 2 * std_dev = %.3f + 2 * %.3f",
                average,
                std_dev,
            )
            return

        #se non è riconosciuta la modalità, si applica "percentile" di default
        self.logger.warning(
            RED + "Detection mode %s non gestita nel controller: uso percentile" + RESET,
            mode,
        )

        percentile = aggregated_stats["percentile"]
        iqr = aggregated_stats["iqr"]
        self.detection.setThreshold(percentile, iqr)

    def _process_detection_round(self):
        
        """
        Calcola soglia e applica detection/mitigation sui flussi raccolti.
        """

        if not self.received_non_empty_stats:
            self.logger.info("All datapaths stats arrived, but all flow tables were empty")
            return

        self.logger.info("All datapaths stats arrived")

        #calcolo e stampo le statistiche dei flussi 
        aggregated_stats = self.statistics.compute_aggregated_dpid_stats(STAT_TO_AGGREGATE)
        self.statistics.display_flow_stats()

        #calcolo la soglia adattiva tramite percentile e intervallo interquartile (IQR) oppure media e deviazione standard
        self._set_adaptive_threshold(aggregated_stats)

        #salvo la soglia realmente usata dalla detection
        threshold_value = self.detection.get_threshold_value()

        self.statistics.append_aggregated_history(
            aggregated=aggregated_stats,
            threshold_value=threshold_value,
            detection_mode=self.detection.mode,
        )

        #aggiorno il grafico delle statistiche aggregate
        self.statistics.plot_aggregated_stats(STAT_TO_AGGREGATE)

        #per ogni flusso, applico detection e mitigation se necessario
        for index in list(self.statistics.flow_stats.index):
            dpid = index[0]
            flow_id = index[1:]

            try:
                computed_flow_stats = self.statistics.flow_stats.loc[index, :].squeeze().to_dict()
            except Exception as exc:
                self.logger.warning("Unable to read stats for flow %s: %s", index, exc)
                continue

            if computed_flow_stats is None:
                continue

            current_value = computed_flow_stats.get(STAT_TO_AGGREGATE, 0) #prendo il valore corrente della statistica da monitorare (flow_rate)
            self._detect_and_mitigate(dpid, flow_id, current_value)

    def _detect_and_mitigate(self, dpid, flow_id, current_value):
        """
        Applica whitelist, blacklist, detection adattiva e mitigation.
        """
        self.mitigation.create_flow_alarm(dpid, flow_id) #inizializzo lo stato dell'allarme per il flusso

        #controllo se il flusso è in whitelist o in blacklist
        white_listed = self.detection.whiteDetection(
            self.policy.get_abilitation_white(str(flow_id))
        )
        black_listed = self.detection.blackDetection(
            self.policy.get_abilitation_black(str(flow_id))
        )

        #se il flusso è in whitelist, non faccio detection e loggo l'informazione
        if white_listed == ListState.LISTED:
            self.logger.info(
                GREEN + "Flow %s on dpid %s is whitelisted: no detection required" + RESET,
                flow_id,
                dpid,
            )
            return

        detected = self.detection.dataDetection(current_value) #controllo se il flow rate corrente supera la soglia adattiva

        #se il flusso è in blacklist, lo blocco subito 
        if black_listed == ListState.LISTED:
            datapath = self.datapaths.get(dpid)
            if datapath:
                self.mitigation.lock_flow(datapath, flow_id)
            return

        #controllo se il flusso era già in stato di allarme e poi incremento
        if detected == FlowState.FLOW_DETECTED:
            
            was_alarm_on = (
                self.mitigation.alarm_flow[dpid][flow_id][1] == AlarmState.ALLARM_ON
            )

            alarm_condition = self.mitigation.increment_flow_alarm(dpid, flow_id)
            is_alarm_on = alarm_condition[1] == AlarmState.ALLARM_ON #controllo se post incremento ho raggiunto lo stato d'allarme

            #se l'allarme era già ON evito di reinstallare la regola di drop
            if is_alarm_on and not was_alarm_on:
                datapath = self.datapaths.get(dpid)
                if datapath is None:
                    self.logger.warning("Datapath %s not found, cannot lock flow %s", dpid, flow_id)
                    return

                self.mitigation.lock_flow(datapath, flow_id) #funzione che installa la regola di drop

        #se il flusso non supera la soglia, viene diminuito il suo stato di allarme
        elif detected == FlowState.FLOW_NO_DETECTION:
            self.mitigation.decrement_flow_alarm(dpid, flow_id)
