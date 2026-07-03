import os
from random import choice, randrange
from time import sleep
from threading import Thread

def run_attack(host, cmd):
    host.cmd(cmd)

class TrafficProfiles: 

        def __init__(
        self,
        net,
        max_attack_stealth=25,
        max_attack_burst=30,
        time_stealth=95,
        log_dir="log"
        ):
        
            self.net = net
            self.log_dir = log_dir

            self.max_attack_stealth = max_attack_stealth
            self.max_attack_burst = max_attack_burst
            self.time_stealth = time_stealth

            # Recupero degli host dalla rete Mininet
            self.h1 = net.get("h1")
            self.h2 = net.get("h2")
            self.h3 = net.get("h3")
            self.h4 = net.get("h4")
            self.h5 = net.get("h5")
            self.h6 = net.get("h6")
            self.h7 = net.get("h7")
            self.h8 = net.get("h8")
            self.h9 = net.get("h9")
            self.h10 = net.get("h10")
            self.h11 = net.get("h11")
            self.h12 = net.get("h12")

            self.list_hosts = [
                self.h1, self.h2, self.h3, self.h4,
                self.h5, self.h6, self.h7, self.h8,
                self.h9, self.h10, self.h11, self.h12
            ]

        def rand_hosts(self, mask = []):
            randHostNum = choice([i for i in range(len(self.list_hosts)) if i + 1 not in mask])
            return self.list_hosts[randHostNum]
        
        def kill_all_traffic(self):

            for host in self.list_hosts:
                host.cmd("pkill -9 iperf || true")
                host.cmd("pkill -9 hping3 || true")
                host.cmd("pkill -9 python3 || true")

        def stealth_attack(self):
            #simula un attacco "stealth" ossia progressivo, con aggiunta graduale di nuovi host che attaccano h1    

            rep = 0 #contatore di ripetizioni
            list_cmd= [] #salva i processi lanciati con popen
            hosts = [] #salva gli host che hanno lanciato l'attacco
            remaining_time = self.time_stealth #copia locale del tempo totale dell'attacco

            self.h1.cmd("timeout 100s python3 -m http.server 80 &") #apro un server http sul port 80 di h1 per 100 secondi
            
            #Traffico di base tra host legittimi  
            self.h1.cmd("(iperf -s -t 95 -p 5002 | tee -a log/stealth/server/logTCPh1.txt) &")
            self.h7.cmd("(iperf -s -t 95 -p 5003 | tee -a log/stealth/server/logTCPh7.txt) &")
            self.h9.cmd("(iperf -s -t 95 -u -p 5004 | tee -a log/stealth/server/logUDPh9.txt) &")

            self.h3.popen("iperf -c 10.0.0.1 -b 2M -t 90 -i 1 -p 5002 | tee -a log/stealth/logh3.txt", shell=True)
            self.h10.popen("iperf -c 10.0.0.7 -b 1M -t 90 -i 1 -p 5003 | tee -a log/stealth/logh10.txt", shell=True)
            self.h5.popen("iperf -u -c 10.0.0.9 -b 1.5M -t 90 -i 1 -p 5004 | tee -a log/stealth/logh5.txt", shell=True)

           
            # Si aggiungono ripetutamente nuovi host che attaccano h1, uno alla volta
            while rep < self.max_attack_stealth:
                wait_time = randrange(3,5)   #attendo 3/4 secondi prima di lanciare un nuovo attacco
                
                src1 = self.rand_hosts(mask = [1, 3, 5, 10]) #scelgo un host random 
                hosts.append(src1)  #aggiungo l'host alla lista degli attaccanti
                traffic = randrange(0,2) #sorteggio il tipo di traffico da generare: 0 = TCP, 1 = UDP

                if traffic == 0: #TCP
                    #costruisco il comando per lanciare l'attacco TCP verso la porta 80 di h1, con pacchetti di 800 byte e intervallo di 1000 microsecondi e durata pari a self.time_stealth secondi
                    cmd = "timeout "+str(self.time_stealth)+"s hping3 -p 80 -i u1000 -d 800 10.0.0.1 >> log/stealth/logAttack.txt"
                else: #UDP
                    #costruisco il comando per lanciare l'attacco UDP verso la porta 80 di h1, con pacchetti di 800 byte e intervallo di 1000 microsecondi e durata pari a self.time_stealth secondi
                    cmd = "timeout "+str(self.time_stealth)+"s hping3 -2 -p 80 -i u1000 -d 800 10.0.0.1 >> log/stealth/logAttack.txt"
                
                print(f"Starting stealth attacker {src1.name}, protocol={traffic}, duration={remaining_time}s")

                p = src1.popen(cmd, shell=True) #lancio il comando
                list_cmd.append(p) 

                sleep(wait_time) #attesa prima di lanciare un nuovo attacco
                
                remaining_time -= wait_time #aggiorno il tempo rimanente dell'attacco
                if remaining_time < 1:
                    remaining_time = 1
                
                rep += 1 #incremento il contatore di ripetizioni
            
            for proc in list_cmd: #attendo la terminazione di tutti i processi lanciati
                proc.wait() 
            for h in hosts: #termino tutti i processi hping3 lanciati dagli host che hanno partecipato all'attacco
                h.cmd("pkill -9 hping3")
    

