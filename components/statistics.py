import json
import math
import os
from enum import Enum
from time import time

import pandas as pd


# codici ANSI utili per colorare le stampe nel terminale
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

#stato restituito da 
class StatisticsState(Enum):

    SETUP_SUCCESS = 1       # lo switch ha inviato almeno un flow valido
    SETUP_EMPTY = 0         # lo switch ha risposto, ma non ci sono flow validi
    SETUP_ERROR = -1        # errore nella preparazione delle statistiche


class Statistics(object):
    """
    Responsabilita:
    - ricevere i flow stats grezzi dagli switch;
    - estrarre flow_id = (in_port, eth_src, eth_dst);
    - calcolare packet_diff e byte_diff tra due campionamenti consecutivi;
    - calcolare flow_rate = byte_diff / time_diff;
    - mantenere un DataFrame con tutte le statistiche correnti;
    - calcolare statistiche aggregate utili alla detection adattiva.
    """

    INDEX_NAMES = ["datapath", "in_port", "eth_src", "eth_dst"]

    COLUMNS = [
        "out_port",     #porta di uscita
        "packet_count", #numero totale di pacchetti visti dallo switch
        "byte_count",   #numero totale di byte
        "packet_diff",  #pacchetti osservati tra due campionamenti consecutivi 
        "byte_diff",    #byte osservati tra due campionamenti consecutivi 
        "flow_rate",    #byte diff / time_diff
        "last_seen",    #ultimo aggiornamento del flusso
    ]

    def __init__(
        self,
        logger,
        statistics_path="jsonFile/statistics.json",
        aggregated_path="jsonFile/aggregatedStats.json",
    ):
        self.logger = logger
        self.statistics_path = statistics_path
        self.aggregated_path = aggregated_path

        os.makedirs("jsonFile", exist_ok=True)

        self.flow_stats = pd.DataFrame(
            columns=self.COLUMNS,
            index=pd.MultiIndex.from_tuples([], names=self.INDEX_NAMES),
        )

        self.current_time_diff = 1.0
        self.current_datapath_id = None
        self.current_raw_flow_stats = []
        self.start_time = time()

    def setup_computations(self, time_diff, datapath_id, raw_flow_stats):
        """
        Prepara il modulo al calcolo delle statistiche per uno specifico switch.

        E chiamata dal controller ogni volta che arriva una FlowStatsReply.

        Parametri:
        - time_diff: tempo trascorso dal campionamento precedente dello stesso switch;
        - datapath_id: id dello switch che ha risposto;
        - raw_flow_stats: lista dei flow filtrati dal controller, quindi priority=1.
        """
        try:
            self.current_time_diff = self._safe_positive_float(time_diff, default=1.0)
            self.current_datapath_id = datapath_id
            self.current_raw_flow_stats = list(raw_flow_stats or [])

            current_indexes = set()


            for raw_flow in self.current_raw_flow_stats:
                flow_id = self._extract_flow_id(raw_flow)
                if flow_id is not None:
                    current_indexes.add((datapath_id,) + flow_id)

            # Rimuove dal DataFrame i flow di questo datapath che non sono piu
            # presenti nella flow table dello switch.
            self._drop_stale_flows_for_datapath(datapath_id, current_indexes)

            if not self.current_raw_flow_stats:
                self.logger.debug("No forwarding flow stats for datapath dpid=%s", datapath_id)
                return StatisticsState.SETUP_EMPTY

            return StatisticsState.SETUP_SUCCESS

        except Exception as exc:
            self.logger.warning(
                RED + "Statistics setup failed for datapath %s: %s" + RESET,
                datapath_id,
                exc,
            )
            return StatisticsState.SETUP_ERROR

    def compute_stat(self, raw_flow_stats):
        """
        Calcola le statistiche aggiornate per un singolo flow.

        Il flow deve essere uno dei flow di forwarding creati da simple_switch13.py:
        match = (in_port, eth_src, eth_dst)
        actions = output:<porta>
        """
        flow_id = self._extract_flow_id(raw_flow_stats)

        if flow_id is None:
            self.logger.debug("Skipping flow without complete id: %s", raw_flow_stats)
            return None

        index = (self.current_datapath_id,) + flow_id

        packet_count = self._safe_non_negative_int(
            getattr(raw_flow_stats, "packet_count", 0)
        )
        byte_count = self._safe_non_negative_int(
            getattr(raw_flow_stats, "byte_count", 0)
        )
        out_port = self._extract_out_port(raw_flow_stats)

        if index in self.flow_stats.index:
            previous_packet_count = self._safe_non_negative_int(
                self.flow_stats.loc[index, "packet_count"]
            )
            previous_byte_count = self._safe_non_negative_int(
                self.flow_stats.loc[index, "byte_count"]
            )

            packet_diff = max(packet_count - previous_packet_count, 0)
            byte_diff = max(byte_count - previous_byte_count, 0)

        else:
            # Primo campionamento del flow:
            # non usiamo i contatori assoluti come traffico recente,
            # altrimenti potremmo generare falsi positivi appena il flow appare.
            packet_diff = 0
            byte_diff = 0

        flow_rate = byte_diff / self.current_time_diff

        row = {
            "out_port": out_port,
            "packet_count": packet_count,
            "byte_count": byte_count,
            "packet_diff": packet_diff,
            "byte_diff": byte_diff,
            "flow_rate": flow_rate,
            "last_seen": time() - self.start_time,
        }

        self._upsert_row(index, row)

        self.logger.debug(
            "Stats dpid=%s flow=%s packet_diff=%s byte_diff=%s flow_rate=%.3f B/s",
            self.current_datapath_id,
            flow_id,
            packet_diff,
            byte_diff,
            flow_rate,
        )

        return row

    def compute_aggregated_dpid_stats(self, stat_to_aggregate):
        """
        Calcola statistiche aggregate sul valore scelto dal controller.

        Nel tuo controller:
        STAT_TO_AGGREGATE = "flow_rate"

        Ritorna sempre un dizionario con almeno:
        - percentile
        - iqr
        - average
        - std_dev
        """
        if stat_to_aggregate not in self.flow_stats.columns:
            self.logger.warning(
                YELLOW + "Statistic %s not present in flow_stats" + RESET,
                stat_to_aggregate,
            )
            return self._empty_aggregated_stats(stat_to_aggregate)

        values = pd.to_numeric(self.flow_stats[stat_to_aggregate], errors="coerce")
        values = values.replace([math.inf, -math.inf], pd.NA).dropna()

        # Per la soglia adattiva usiamo i valori positivi.
        # Gli zeri iniziali dei flow appena creati non devono abbassare artificialmente la soglia.
        positive_values = values[values > 0]

        if positive_values.empty:
            aggregated = self._empty_aggregated_stats(stat_to_aggregate)
        else:
            percentile25 = float(positive_values.quantile(0.25))
            percentile75 = float(positive_values.quantile(0.75))
            iqr = percentile75 - percentile25

            aggregated = {
                "stat": stat_to_aggregate,
                "count": int(positive_values.count()),
                "min": float(positive_values.min()),
                "max": float(positive_values.max()),
                "average": float(positive_values.mean()),
                "std_dev": float(positive_values.std(ddof=0)),
                "percentile25": percentile25,
                "percentile": percentile75,   # nome mantenuto per compatibilita col controller
                "percentile75": percentile75,
                "iqr": float(iqr),
                "computed_at": time() - self.start_time,
            }

        self._write_json(self.aggregated_path, aggregated)

        self.logger.info(
            "Aggregated %s: count=%d avg=%.3f p75=%.3f iqr=%.3f",
            stat_to_aggregate,
            aggregated["count"],
            aggregated["average"],
            aggregated["percentile"],
            aggregated["iqr"],
        )

        return aggregated

    def display_flow_stats(self):
        """
        Salva le statistiche correnti su jsonFile/statistics.json e stampa un riepilogo nei log.
        """
        records = self._flow_stats_to_records()
        self._write_json(self.statistics_path, records)

        if not records:
            self.logger.info("No flow statistics to display")
            return

        self.logger.info(
            GREEN + "Flow statistics updated: %d active forwarding flow(s)" + RESET,
            len(records),
        )

        for record in records:
            self.logger.info(
                "dpid=%s in_port=%s src=%s dst=%s out=%s packets=%s bytes=%s "
                "packet_diff=%s byte_diff=%s flow_rate=%.3f B/s",
                record["datapath"],
                record["in_port"],
                record["eth_src"],
                record["eth_dst"],
                record["out_port"],
                record["packet_count"],
                record["byte_count"],
                record["packet_diff"],
                record["byte_diff"],
                record["flow_rate"],
            )

    def _extract_flow_id(self, raw_flow_stats):
        """
        Estrae flow_id = (in_port, eth_src, eth_dst) da un flow OpenFlow.
        """
        try:
            match = raw_flow_stats.match

            in_port = match.get("in_port")
            eth_src = match.get("eth_src")
            eth_dst = match.get("eth_dst")

            if in_port is None or eth_src is None or eth_dst is None:
                return None

            return (int(in_port), str(eth_src), str(eth_dst))

        except Exception as exc:
            self.logger.debug("Unable to extract flow_id: %s", exc)
            return None

    def _extract_out_port(self, raw_flow_stats):
        """
        Estrae la porta di output dalla prima action del flow.

        Nei flow creati dal simple_switch13.py la forma e:
        instruction -> action output:<porta>
        """
        try:
            instructions = getattr(raw_flow_stats, "instructions", [])
            if not instructions:
                return None

            actions = getattr(instructions[0], "actions", [])
            if not actions:
                return None

            return getattr(actions[0], "port", None)

        except Exception:
            return None

    def _drop_stale_flows_for_datapath(self, datapath_id, current_indexes):
        """
        Rimuove i flow di uno switch che non compaiono piu nell'ultima FlowStatsReply.

        Serve a evitare che la detection lavori su flow vecchi non piu presenti.
        """
        if self.flow_stats.empty:
            return

        indexes_to_drop = [
            index
            for index in self.flow_stats.index
            if index[0] == datapath_id and index not in current_indexes
        ]

        if indexes_to_drop:
            self.flow_stats = self.flow_stats.drop(index=indexes_to_drop)
            self.logger.debug(
                "Dropped %d stale flow(s) for datapath dpid=%s",
                len(indexes_to_drop),
                datapath_id,
            )

    def _upsert_row(self, index, row):
        """
        Inserisce o aggiorna una riga del DataFrame.
        """
        if index in self.flow_stats.index:
            for column, value in row.items():
                self.flow_stats.loc[index, column] = value
            return

        new_row = pd.DataFrame(
            [row],
            index=pd.MultiIndex.from_tuples([index], names=self.INDEX_NAMES),
        )

        self.flow_stats = pd.concat([self.flow_stats, new_row], axis=0)

    def _flow_stats_to_records(self):
        """
        Converte il DataFrame in una lista di dizionari serializzabile in JSON.
        """
        if self.flow_stats.empty:
            return []

        reset_df = self.flow_stats.reset_index()
        records = []

        for _, row in reset_df.iterrows():
            records.append(
                {
                    "datapath": self._to_json_number(row["datapath"]),
                    "in_port": self._to_json_number(row["in_port"]),
                    "eth_src": row["eth_src"],
                    "eth_dst": row["eth_dst"],
                    "out_port": self._to_json_number(row["out_port"]),
                    "packet_count": self._to_json_number(row["packet_count"]),
                    "byte_count": self._to_json_number(row["byte_count"]),
                    "packet_diff": self._to_json_number(row["packet_diff"]),
                    "byte_diff": self._to_json_number(row["byte_diff"]),
                    "flow_rate": self._to_json_number(row["flow_rate"]),
                    "last_seen": self._to_json_number(row["last_seen"]),
                }
            )

        return records

    def _empty_aggregated_stats(self, stat_to_aggregate):
        """
        Ritorna statistiche aggregate nulle ma compatibili col controller.
        """
        aggregated = {
            "stat": stat_to_aggregate,
            "count": 0,
            "min": 0.0,
            "max": 0.0,
            "average": 0.0,
            "std_dev": 0.0,
            "percentile25": 0.0,
            "percentile": 0.0,
            "percentile75": 0.0,
            "iqr": 0.0,
            "computed_at": time() - self.start_time,
        }

        self._write_json(self.aggregated_path, aggregated)
        return aggregated

    #converte l'argomento in float positivo
    def _safe_positive_float(self, value, default=1.0):
        
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default

        if math.isnan(value) or math.isinf(value) or value <= 0:
            return default

        return value
    
    #converte l'argomento in float negativo
    def _safe_non_negative_int(self, value, default=0):

        try:
            value = int(value)
        except (TypeError, ValueError):
            return default

        if value < 0:
            return default

        return value

    def _to_json_number(self, value):
        """
        Converte tipi pandas/numpy in tipi Python serializzabili in JSON.
        """
        if pd.isna(value):
            return None

        try:
            number = float(value)
        except (TypeError, ValueError):
            return value

        if math.isnan(number) or math.isinf(number):
            return None

        if number.is_integer():
            return int(number)

        return number

    def _write_json(self, path, data):
        """
        Scrive un oggetto Python in JSON.
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, "w") as file:
            json.dump(data, file, indent=2)
