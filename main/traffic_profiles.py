from itertools import tee
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
        max_attack_stealth=20, #numero di host che partecipano all'attacco stealth, poiché ciascun inserimento progressivo dura 3/4 secondi, conviene limitare il numero di host a 20 
        max_attack_burst=10, #i server sono settati per durare 120 secondi e ogni burst dura, comprese le pause, al più 8 secondi => il massimo numero di burst è 15 
        time_stealth=95, #durata totale dell'attacco stealth
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

        #crea le directory per i log 
        def ensure_log_dirs(self, scenario): 
            os.makedirs(f"{self.log_dir}/{scenario}", exist_ok=True)
            os.makedirs(f"{self.log_dir}/{scenario}/server", exist_ok=True)

        #sceglie un host random tra quelli disponibili, escludendo quelli specificati nella maschera
        def rand_hosts(self, mask = []):
            randHostNum = choice([i for i in range(len(self.list_hosts)) if i + 1 not in mask])
            return self.list_hosts[randHostNum]
        
        def kill_all_traffic(self):

            for host in self.list_hosts:
                host.cmd("pkill -9 iperf || true")
                host.cmd("pkill -9 hping3 || true")
                host.cmd("pkill -9 python3 || true")

        def stealth_attack(self):
            #simula un attacco "stealth" ossia progressivo, con aggiunta graduale di nuovi host che attaccano h1 mentre il traffico legittimo continua tra gli altri host

            rep = 0 #contatore di ripetizioni
            list_cmd= [] #salva i processi lanciati con popen
            hosts = [] #salva gli host che hanno lanciato l'attacco
            remaining_time = self.time_stealth #copia locale del tempo totale dell'attacco

            self.h1.cmd("timeout 100s python3 -m http.server 80 &") #apro un server http sul port 80 di h1 per 100 secondi
            
            #Traffico di base tcp e udptra host legittimi  
            self.h1.cmd("(iperf -s -t 95 -p 5002 | tee -a log/stealth/server/logTCPh1.txt) &")
            self.h7.cmd("(iperf -s -t 95 -p 5003 | tee -a log/stealth/server/logTCPh7.txt) &")
            self.h9.cmd("(iperf -s -t 95 -u -p 5004 | tee -a log/stealth/server/logUDPh9.txt) &")

            p1 = self.h3.popen("iperf -u -c 10.0.0.1 -b 300K -t 90 -i 1 -p 5002 | tee -a log/stealth/logh3.txt", shell=True)
            list_cmd.append(p1)
            p2 = self.h10.popen("sleep 5; for i in $(seq 1 15); do iperf -c 10.0.0.7 -n 300K -p 5003 -i 1 | tee -a log/stealth/logh10.txt; sleep 3; done", shell=True)
            list_cmd.append(p2)
            p3 = self.h5.popen("iperf -u -c 10.0.0.9 -b 300K -t 90 -i 1 -p 5004 | tee -a log/stealth/logh5.txt", shell=True)
            list_cmd.append(p3)

           
            # Si aggiungono ripetutamente nuovi host che attaccano h1, uno alla volta
            while rep < self.max_attack_stealth:
                wait_time = randrange(3,5)   #attendo 3/4 secondi prima di lanciare un nuovo attacco
                
                src1 = self.rand_hosts(mask = [1, 3, 5, 10]) #scelgo un host random 
                hosts.append(src1)  #aggiungo l'host alla lista degli attaccanti
                traffic = randrange(0,2) #sorteggio il tipo di traffico da generare: 0 = TCP, 1 = UDP

                if traffic == 0: #TCP
                    #costruisco il comando per lanciare l'attacco TCP verso la porta 80 di h1, con pacchetti di 800 byte e intervallo di 1000 microsecondi e durata pari a self.time_stealth secondi
                    cmd = "timeout "+str(remaining_time)+"s hping3 -p 80 -i u1000 -d 800 10.0.0.1 >> log/stealth/logAttack.txt"
                else: #UDP
                    #costruisco il comando per lanciare l'attacco UDP verso la porta 80 di h1, con pacchetti di 800 byte e intervallo di 1000 microsecondi e durata pari a self.time_stealth secondi
                    cmd = "timeout "+str(remaining_time)+"s hping3 -2 -p 80 -i u1000 -d 800 10.0.0.1 >> log/stealth/logAttack.txt"
                
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
    
        def burst_attack(self):
            #simula un attacco "burst" ossia improvviso, il solo host h1 attacca h6 mentre h2, h3, h4 e h5 generano traffico legittimo verso h6, h10, h7 e h9 rispettivamente

            rep = 0
            list_cmd= [] #salva i processi lanciati con popen

            self.h6.cmd("timeout 130s python3 -m http.server 80 &") #apro un server http sul port 80 di h6 per 130 secondi
            
            #traffico di base tcp e udp tra host legittimi

            self.h6.cmd("(iperf -t 120 -s | tee -a log/burst/server/logTCPh6.txt) &") 
            self.h10.cmd("(iperf -s -t 120 -p 5002 | tee -a log/burst/server/logTCPh10.txt) &") 
            self.h7.cmd("(iperf -s -t 120 -p 5003 | tee -a log/burst/server/logTCPh7.txt) &")
            self.h9.cmd("(iperf -s -t 120 -u -p 5004 | tee -a log/burst/server/logUDPh9.txt) &")
       
            sleep(2) #attendo 2 secondi prima di lanciare il traffico legittimo

            #i client sono tutti udp tranne h4, hanno una banda limitata a 300KBit/s e partono scaglionati
            p1 = self.h2.popen("sleep 2; iperf -u -c 10.0.0.6 -b 300K -t 70 -i 1 -p 5001 | tee -a log/burst/logh2.txt", shell=True)
            list_cmd.append(p1)
            p2 = self.h3.popen("sleep 5; iperf -u -c 10.0.0.10 -b 300K -t 70 -i 1 -p 5002 | tee -a log/burst/logh3.txt", shell=True)
            list_cmd.append(p2)
            p3 = self.h4.popen("sleep 8; for i in $(seq 1 15); do iperf -c 10.0.0.7 -n 300K -p 5003 -i 1 | tee -a log/burst/logh4.txt; sleep 3; done", shell=True)
            list_cmd.append(p3)
            p4 = self.h5.popen("iperf -u -c 10.0.0.9 -b 300K -t 90 -i 1 -p 5004 | tee -a log/burst/logh5.txt", shell=True)
            list_cmd.append(p4)

            sleep(2)

            while rep < self.max_attack_burst: #ripeto l'attacco per un numero di volte pari a self.max_attack_burst
                
                wait_time = randrange(4,8) #attendo 4-7 secondi tra un attacco e l'altro

                print(
                        f"Starting burst attack {rep + 1}/{self.max_attack_burst}: "
                        f"attacker={self.h1.name}, victim={self.h6.name}, "
                        f"protocol=UDP, duration=20s, next_pause={wait_time}s",
                        flush=True
                    )

                # lancio l'attacco verso h6 con pacchetti di 3000 byte e flood mode, per un tempo di 20 secondi
                self.h1.cmd("timeout 20s hping3 -2 -V --flood -p 80 -d 3000 10.0.0.6 >> log/burst/logAttack.txt")     
                sleep(wait_time) #attesa prima di lanciare un nuovo attacco
                self.h1.cmd("pkill -9 hping3") #termino eventuali processi hping3 rimasti in esecuzione
                rep += 1 #incremento il contatore di ripetizioni
            
            for proc in list_cmd: #attendo la terminazione di tutti i processi lanciati
                proc.wait()

        
        def custom_attack(self):
        #attacco personalizzato che simula un DDoS con 4 attaccanti rivolto ad h6, con traffico legittimo tra gli altri host della rete
        
            list_cmd = [] #salva i processi lanciati con popen

            self.h6.cmd("timeout 120s python3 -m http.server 80 &") #apro un server http sul port 80 di h6 per 120 secondi

            #Traffico di base tcp e udp tra host legittimi
            self.h6.cmd("(iperf -t 100 -s | tee -a log/custom/server/logTCPh6.txt) &")
            self.h3.cmd("(iperf -u -t 100 -s -p 5002 | tee -a log/custom/server/logUDPh3.txt) &") #UDP
            self.h4.cmd("(iperf -s -t 100 -p 5003 | tee -a log/custom/server/logTCPh4.txt) &") #TCP 

            sleep(2) #attendo 2 secondi prima di lanciare il traffico legittimo

            #gli host benevoli in trasmissione sono h1, h7 e h10
            p1 = self.h1.popen("sleep 3; iperf -u -c 10.0.0.6 -b 300K -t 95 -i 1 -p 5001 | tee -a log/custom/logh1toh6.txt", shell=True)
            list_cmd.append(p1)
            p2 = self.h10.popen("sleep 5; for i in $(seq 1 15); do iperf -c 10.0.0.4 -n 300K -p 5003 -i 1 | tee -a log/custom/logh10toh4.txt; sleep 3; done", shell=True)
            list_cmd.append(p2)
            p3 = self.h7.popen("iperf -u -c 10.0.0.3 -b 300K -t 95 -i 1 -p 5002 | tee -a log/custom/logh7toh3.txt", shell=True)
            list_cmd.append(p3) 

            sleep(4) #attendo 4 secondi prima di lanciare l'attacco

            thr = [] #salva i thread che lanciano gli attacchi

            #definisco i 4 attacchi verso h6, due UDP e due TCP, ogni attacco dura 95 secondi, con pacchetti di 1400/1450 byte e intervallo di 250 microsecondi
            attacks = [
                (self.h2, "timeout 95s hping3 -2 -V -i u250 -p 80 -d 1450 10.0.0.6 >> log/custom/logh2Attack.txt"), #UDP
                (self.h5, "timeout 95s hping3 -V --flood -p 80 -d 1400 10.0.0.6 >> log/custom/logh5Attack.txt"), #TCP 
                (self.h8, "timeout 95s hping3 -2 -V -i u250 -p 80 -d 1450 10.0.0.6 >> log/custom/logh8Attack.txt"), #UDP
                (self.h9, "timeout 95s hping3 -V --flood -p 80 -d 1400 10.0.0.6 >> log/custom/logh9Attack.txt"), #TCP 
                ]

            # lancio gli attacchi in parallelo utilizzando thread
            for host, cmd in attacks: 

                print(
                    f"Starting custom attack: attacker={host.name}, "
                    f"victim=h6, duration=95s",
                    flush=True
                )

                t = Thread(target=run_attack, args=(host, cmd)) 
                t.start()
                thr.append(t)

            for t in thr: #attendo la terminazione di tutti i thread che hanno lanciato gli attacchi
                t.join()

            for proc in list_cmd: #attendo la terminazione di tutti i processi lanciati per il traffico legittimo
                proc.wait()

            for host, _ in attacks: #termino eventuali processi hping3 rimasti in esecuzione sugli host attaccanti
                host.cmd("pkill -9 hping3")
                
