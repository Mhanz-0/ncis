import time

from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER


class Monitoring(object):
    """
    Responsabilità:
    - registrare/rimuovere gli switch connessi al controller;
    - inviare richieste OpenFlow di flow statistics agli switch;
    - restituire il timestamp della richiesta, utile al controller se vuole misurare tempi.
    """

    def __init__(self, logger):
        self.logger = logger

    #gestisce la connessione e disconnessione degli switch al controller, sono organizzati in dizionari del tipo dpid:datapath
    def state_change_handler(self, ev, datapaths):

        datapath = ev.datapath

        #lo switch è connesso al controller ed è pronto
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in datapaths:
                datapaths[datapath.id] = datapath  #registro lo switch se non è già nel dizionario 
                self.logger.info("Registered datapath dpid=%s", datapath.id)

        #lo switch non è più connesso/non è valido
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in datapaths:
                datapaths.pop(datapath.id, None)    #rimozione dello switch dal dizionario
                self.logger.info("Unregistered datapath dpid=%s", datapath.id)


    #mando a uno switch una richiesta OpenFlow di statistiche sul flusso
    def _request_stats(self, datapath):
        
        parser = datapath.ofproto_parser

        request = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(request)

        self.logger.debug("Sent FlowStatsRequest to datapath dpid=%s", datapath.id)

        return time.perf_counter()
