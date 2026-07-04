from enum import Enum
import math

#codici ANSI utili per colorare le stampe nel terminale
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

#risultato della detection sul singolo flusso 
class FlowState(Enum):

    FLOW_DETECTED = 1          #flusso sospetto
    FLOW_NO_DETECTION = -1     #flusso legittimo

#risultato del controllo whitelist/blacklist
class ListState(Enum):

    LISTED = -1        #il flusso è in whitelist/blacklist
    NOT_LISTED = 1     #il flusso non è listato


class Detection(object):
    """
    Modalita disponibili:
    - "percentile": soglia = percentile75 + 1.5 * IQR
    - "average&std_dev": soglia = average + 2 * std_dev
    - "average": soglia = average + average * percentage / 100
    """

    VALID_MODES = ("percentile", "average&std_dev", "average")

    #la modalità percentile è settata di default e anche quando si sceglie una modalità invalida
    def __init__(self, logger, mode="percentile"):
        self.logger = logger
        self.threshold = tuple()

        if mode not in self.VALID_MODES:
            self.logger.warning(
                RED + "Detection mode %s non valida: uso 'percentile'" + RESET,
                mode,
            )
            mode = "percentile"

        self.mode = mode
        self.last_threshold_value = None

    #salva i parametri della soglia
    def setThreshold(self, *threshold):

        self.threshold = threshold

    #converte un valore in float
    def _to_float(self, value, default=0.0):
        
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default

        if math.isnan(value) or math.isinf(value):
            return default

        return value

    #calcola il valore della soglia in base alla modalità scelta
    def _compute_threshold_value(self):

        if len(self.threshold) < 2:
            self.logger.debug("Detection threshold non ancora impostata")
            return None

        first = self._to_float(self.threshold[0])
        second = self._to_float(self.threshold[1])

        if self.mode == "percentile":
            percentile = first
            iqr = second
            return percentile + 1.5 * iqr

        if self.mode == "average&std_dev":
            average = first
            std_dev = second
            return average + 2.0 * std_dev

        if self.mode == "average":
            average = first
            percentage = second
            return average + (average / 100.0) * percentage

        self.logger.warning(RED + "Modalita detection non valida: %s" + RESET, self.mode)
        return None

    #decide se il valore corrente del flowrate è sospetto
    def dataDetection(self, flow):

        #recupero il valore e calcolo la soglia
        flow_value = self._to_float(flow)
        threshold_value = self._compute_threshold_value()
        self.last_threshold_value = threshold_value

        if threshold_value is None:
            return FlowState.FLOW_NO_DETECTION

        if flow_value > threshold_value: 
            self.logger.warning(
                RED + "Flow detected: value=%.3f threshold=%.3f mode=%s" + RESET,
                flow_value,
                threshold_value,
                self.mode,
            )
            return FlowState.FLOW_DETECTED

        self.logger.debug(
            GREEN + "Flow normal: value=%.3f threshold=%.3f mode=%s" + RESET,
            flow_value,
            threshold_value,
            self.mode,
        )
        return FlowState.FLOW_NO_DETECTION

    #entrambe le detection seguenti restituiscono LISTED se il flusso è presente rispettivamente in whitelist o blacklist

    def whiteDetection(self, white_cond):

        if bool(white_cond):
            return ListState.LISTED
        return ListState.NOT_LISTED

    def blackDetection(self, black_cond):

        if bool(black_cond):
            return ListState.LISTED
        return ListState.NOT_LISTED
