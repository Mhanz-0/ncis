import json
import os
import tempfile
from logging import FileHandler
from time import time

from ryu.lib import hub

#codici ANSI utili per colorare le stampe nel terminale
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


class Policy(object):
    """
    Responsabilità:
    - leggere periodicamente whitelist e blacklist da file JSON;
    - fornire al controller metodi per sapere se un flow è whitelistato/blacklistato;
    - permettere a moduli esterni, GUI o admin di aggiungere/rimuovere policy;
    - mantenere la logica di policy separata da detection e mitigation.

    Formato consigliato dei file JSON:

    {
        "(1, '00:00:00:00:00:05', '00:00:00:00:00:06')": {
            "enabled": true,
            "reason": "trusted server flow"
        }
    }

    La chiave è str(flow_id), dove nel controller:
    flow_id = (in_port, eth_src, eth_dst)
    """

    def __init__(
        self,
        logger,
        white_list_path="jsonFile/whiteList.json",
        black_list_path="jsonFile/blackList.json",
        update_interval=1.0,                         #specifica quanto aspetta il controller prima di rileggere i file json
    ):
        self.logger = logger

        self.white_list_path = white_list_path
        self.black_list_path = black_list_path
        self.update_interval = update_interval

        # Dizionari caricati dai JSON.
        self.whiteList = {}
        self.blackList = {}

        self.start_time = time()  #salvo il tempo di creazione dell'oggetto

        self._ensure_files()
        self._load_lists()


    #crea cartella e file json se non esistono già
    def _ensure_files(self):
      
        os.makedirs(os.path.dirname(self.white_list_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.black_list_path), exist_ok=True)

        for path in (self.white_list_path, self.black_list_path):
            if not os.path.exists(path):
                self._atomic_write_json(path, {})

    #carica whitelist e blacklist dai rispettivi file
    def _load_lists(self):
     
        self.whiteList = self._read_json_dict(self.white_list_path)
        self.blackList = self._read_json_dict(self.black_list_path)

        self.logger.debug(
            "Policy loaded: whitelist=%d entries, blacklist=%d entries",
            len(self.whiteList),
            len(self.blackList),
        )

    #scrive un json in modo atomico: sostituisce il file reale solo dopo aver terminato la scrittura su un file temporaneo per evitare file corrotti dovuti ad interruzioni improvvise
    def _atomic_write_json(self, path, data):
        
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)

        #creo qui il file temporaneo
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp_policy_", suffix=".json", dir=directory)

        #apro il file temporaneo in scrittura e copio il dizionario contenuto in "data"
        try:
            with os.fdopen(fd, "w") as tmp_file:
                json.dump(data, tmp_file, indent=2)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            os.replace(tmp_path, path) #sostituisco il file finale con quello temporaneo

        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    #legge un file json e restituisce un dizionario
    def _read_json_dict(self, path):
 
        try:
            with open(path, "r") as file:
                content = file.read().strip()

            if not content:      #se il file è vuoto ritorna un dizionario vuoto
                return {}

            data = json.loads(content)  #conversione json in oggetto python 

            if isinstance(data, dict):
                return data

            #supporto opzionale se qualcuno scrive una lista di flow_id
            if isinstance(data, list):
                return {str(item): {"enabled": True} for item in data}

            #il warning è lanciato se il json non contiene né un dizionario né una lista
            self.logger.warning(
                YELLOW + "Policy file %s does not contain dict/list, ignoring it" + RESET,
                path,
            )
            return {}

        except FileNotFoundError:
            self.logger.warning(YELLOW + "Policy file %s not found, recreating it" + RESET, path)
            self._atomic_write_json(path, {})
            return {}

        except json.JSONDecodeError as exc:
            self.logger.warning(
                RED + "Invalid JSON in policy file %s: %s" + RESET,
                path,
                exc,
            )
            return {}

        except OSError as exc:
            self.logger.warning(
                RED + "Cannot read policy file %s: %s" + RESET,
                path,
                exc,
            )
            return {}

    
    #thread periodico per rileggere i json ogni update_interval secondi
    def update_lists(self):

        while True:
            self._load_lists()
            hub.sleep(self.update_interval)

    #verifica se la chiave di un flusso è presenta e abilitata in una policy
    def _is_policy_enabled(self, policy_dict, flow_key):
        """
        Accetta più formati:

        "flow": true
        "flow": false
        "flow": {"enabled": true}
        "flow": {"enabled": false}
        "flow": {"reason": "..."}          -> considerato enabled=True
        "flow": ["qualunque", "lista"]     -> considerato enabled=True
        """
        flow_key = str(flow_key)

        if flow_key not in policy_dict:                    #ritorna falso se non presente nella lista
            return False

        value = policy_dict[flow_key]

        if isinstance(value, bool):                        #se il valore è booleano lo ritorna immediatamente
            return value

        if isinstance(value, dict):                        #se il valore è un dizionario cerca il campo "enabled"
            return bool(value.get("enabled", value.get("abilitation", True)))

        # Se la chiave esiste ma il valore non è booleano o dizionario, la policy è considerata attiva
        return True

    #restitusce vero se il flusso è presente e abilitato in whitelist
    def get_abilitation_white(self, flow_key):

        return self._is_policy_enabled(self.whiteList, flow_key)

    #restituisce vero se il flusso è presente e abilitato in blacklist
    def get_abilitation_black(self, flow_key):

        return self._is_policy_enabled(self.blackList, flow_key)

    #aggiunge un flusso alla whitelist e lo salva nel file json
    def add_to_white_list(self, flow_key, reason="manual whitelist", enabled=True):
     
        flow_key = str(flow_key)

        self.whiteList[flow_key] = {
            "enabled": bool(enabled),
            "reason": reason,
            "created_at": time(),
        }

        self._atomic_write_json(self.white_list_path, self.whiteList)

        self.logger.info(
            GREEN + "Added flow to whitelist: %s" + RESET,
            flow_key,
        )

    #aggiunge un flusso alla blacklist e lo salva nel file json 
    def add_to_black_list(self, flow_key, reason="manual blacklist", enabled=True):
       
        flow_key = str(flow_key)

        self.blackList[flow_key] = {
            "enabled": bool(enabled),
            "reason": reason,
            "created_at": time(),
        }

        self._atomic_write_json(self.black_list_path, self.blackList)

        self.logger.info(
            RED + "Added flow to blacklist: %s" + RESET,
            flow_key,
        )

    #rimuove un flusso dalla whitelist
    def remove_from_white_list(self, flow_key):
        
        flow_key = str(flow_key)

        if flow_key in self.whiteList:
            self.whiteList.pop(flow_key, None)
            self._atomic_write_json(self.white_list_path, self.whiteList)
            self.logger.info("Removed flow from whitelist: %s", flow_key)

    #rimuove un flusso dalla blacklist
    def remove_from_black_list(self, flow_key):

        flow_key = str(flow_key)

        if flow_key in self.blackList:
            self.blackList.pop(flow_key, None)
            self._atomic_write_json(self.black_list_path, self.blackList)
            self.logger.info("Removed flow from blacklist: %s", flow_key)

    #abilita/disabilita una entry della whitelist senza rimuoverla
    def set_white_enabled(self, flow_key, enabled):
    
        flow_key = str(flow_key)

        if flow_key not in self.whiteList:
            return

        if isinstance(self.whiteList[flow_key], dict):
            self.whiteList[flow_key]["enabled"] = bool(enabled)
        else:
            self.whiteList[flow_key] = bool(enabled)

        self._atomic_write_json(self.white_list_path, self.whiteList)

    #abilita/disabilita una entry della blacklist senza rimuoverla
    def set_black_enabled(self, flow_key, enabled):
  
        flow_key = str(flow_key)

        if flow_key not in self.blackList:
            return

        if isinstance(self.blackList[flow_key], dict):
            self.blackList[flow_key]["enabled"] = bool(enabled)
        else:
            self.blackList[flow_key] = bool(enabled)

        self._atomic_write_json(self.black_list_path, self.blackList)
