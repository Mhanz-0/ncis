import os
from datetime import datetime
from time import sleep

class ScenarioRunner:
       
        def __init__(self, net, profiles):
            self.net = net
            self.profiles = profiles

            self.base_log_dir = "log"

        #crea un timestamp per i log
        def _timestamp(self):
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        #crea le directory per i log dello scenario specificato
        def _ensure_log_dirs(self, scenario_name):
            os.makedirs(f"{self.base_log_dir}/{scenario_name}", exist_ok=True)
            os.makedirs(f"{self.base_log_dir}/{scenario_name}/server", exist_ok=True)

        #scrive un file info.txt con le informazioni dello scenario specificato
        def _write_scenario_info(self, scenario_name):
 
            info_path = f"{self.base_log_dir}/{scenario_name}/info.txt"

            with open(info_path, "a") as f:
                f.write("\n")
                f.write("=" * 60 + "\n")
                f.write(f"Scenario: {scenario_name}\n")
                f.write(f"Started at: {self._timestamp()}\n")
                f.write("=" * 60 + "\n")

        #pulisce i processi hping3, iperf e http.server rimasti in esecuzione sugli host della rete
        def cleanup(self):

            print("[CLEANUP] Killing old hping3, iperf and http.server processes...", flush=True)

            for host in self.net.hosts:
                host.cmd("pkill -9 hping3 || true")
                host.cmd("pkill -9 iperf || true")
                host.cmd("pkill -f 'python3 -m http.server' || true")

            sleep(1)

            print("[CLEANUP] Done.", flush=True)

        #esegue un pingall per verificare la connettività della rete
        def check_connectivity(self):

            print("[CHECK] Running pingall before scenario...", flush=True)
            loss = self.net.pingAll()

            print(f"[CHECK] pingall packet loss: {loss}%", flush=True)

            return loss
        
        #lancia lo scenario stealth_attack 
        def run_stealth(self, check=True, cleanup_before=True, cleanup_after=True):

            scenario_name = "stealth"

            print("\n" + "=" * 70, flush=True) 
            print("[SCENARIO] Starting STEALTH ATTACK scenario", flush=True)
            print("=" * 70, flush=True)

            self._ensure_log_dirs(scenario_name)
            self._write_scenario_info(scenario_name)

            if cleanup_before: 
                self.cleanup()

            if check:
                self.check_connectivity()

            print("[SCENARIO] Launching profiles.stealth_attack()", flush=True)

            self.profiles.stealth_attack()

            print("[SCENARIO] STEALTH ATTACK completed.", flush=True)

            if cleanup_after:
                self.cleanup()

        #lancia lo scenario burst_attack
        def run_burst(self, check=True, cleanup_before=True, cleanup_after=True):

            scenario_name = "burst"

            print("\n" + "=" * 70, flush=True)
            print("[SCENARIO] Starting BURST ATTACK scenario", flush=True)
            print("=" * 70, flush=True)

            self._ensure_log_dirs(scenario_name)
            self._write_scenario_info(scenario_name)

            if cleanup_before:
                self.cleanup()

            if check:
                self.check_connectivity()

            print("[SCENARIO] Launching profiles.burst_attack()", flush=True)

            self.profiles.burst_attack()

            print("[SCENARIO] BURST ATTACK completed.", flush=True)

            if cleanup_after:
                self.cleanup()

        #lancia lo scenario custom_attack
        def run_custom(self, check=True, cleanup_before=True, cleanup_after=True):

            scenario_name = "custom"

            print("\n" + "=" * 70, flush=True)
            print("[SCENARIO] Starting CUSTOM ATTACK scenario", flush=True)
            print("=" * 70, flush=True)

            self._ensure_log_dirs(scenario_name)
            self._write_scenario_info(scenario_name)

            if cleanup_before:
                self.cleanup()

            if check:
                self.check_connectivity()
            
            print("[SCENARIO] Launching custom attack profile", flush=True)

            self.profiles.custom_attack()

            print("[SCENARIO] CUSTOM ATTACK completed.", flush=True)

            if cleanup_after:
                self.cleanup()

        #lancia tutti gli scenari in sequenza nell'ordine stealth->burst->custom
        def run_all(self, pause_between=10, check=True):
        
            print("\n" + "#" * 70, flush=True)
            print("[EXPERIMENT] Running all scenarios", flush=True)
            print("#" * 70, flush=True)

            self.run_stealth(check=check, cleanup_before=True, cleanup_after=True)

            print(f"[EXPERIMENT] Waiting {pause_between}s before next scenario...", flush=True)
            sleep(pause_between)

            self.run_burst(check=check, cleanup_before=True, cleanup_after=True)
            print(f"[EXPERIMENT] Waiting {pause_between}s before next scenario...", flush=True)
            sleep(pause_between)

            self.run_custom(check=check, cleanup_before=True, cleanup_after=True)

            print("\n" + "#" * 70, flush=True)
            print("[EXPERIMENT] All scenarios completed.", flush=True)
            print("#" * 70, flush=True)

        #lancia uno scenario in base al nome fornito come argomento tra "stealth", "burst", "custom" o "all"
        def run(self, scenario_name):

            scenario_name = scenario_name.lower()

            if scenario_name == "stealth":
                self.run_stealth()
            elif scenario_name == "burst":
                self.run_burst()
            elif scenario_name == "custom":
                self.run_custom()
            elif scenario_name == "all":
                self.run_all()
            else:
                raise ValueError(
                    "Unknown scenario. Use: stealth, burst, custom, all"
                )
