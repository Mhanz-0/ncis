from mininet.log import setLogLevel, info
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.node import OVSKernelSwitch
from mininet.link import TCLink
from mininet.node import RemoteController #Controller
from mininet.term import makeTerm
from random import choice, randrange
from time import sleep
from threading import Thread
from traffic_profiles import TrafficProfiles

class Environment(object):

    def __init__(self):
        
        #creazione della rete
        self.net = Mininet(controller=RemoteController, link=TCLink)
        info("*** Starting baseline controller\n")
        c1 = self.net.addController('c1', controller=RemoteController, port=6633)
        c1.start()

        info("*** Starting custom controller\n")
        c2 = self.net.addController('c2', controller=RemoteController, port=6634)
        c2.start()

        info("*** Host and switches creation\n")
        self.h1 = self.net.addHost('h1',mac='00:00:00:00:00:01',ip='10.0.0.1')
        self.h2 = self.net.addHost('h2',mac='00:00:00:00:00:02',ip='10.0.0.2')
        self.h3 = self.net.addHost('h3',mac='00:00:00:00:00:03',ip='10.0.0.3')
        self.h4 = self.net.addHost('h4',mac='00:00:00:00:00:04',ip='10.0.0.4')
        self.h5 = self.net.addHost('h5',mac='00:00:00:00:00:05',ip='10.0.0.5')
        self.h6 = self.net.addHost('h6',mac='00:00:00:00:00:06',ip='10.0.0.6')
        self.h7 = self.net.addHost('h7',mac='00:00:00:00:00:07',ip='10.0.0.7')
        self.h8 = self.net.addHost('h8',mac='00:00:00:00:00:08',ip='10.0.0.8')
        self.h9 = self.net.addHost('h9',mac='00:00:00:00:00:09',ip='10.0.0.9')
        self.h10 = self.net.addHost('h10',mac='00:00:00:00:00:10',ip='10.0.0.10')
        self.h11 = self.net.addHost('h11',mac='00:00:00:00:00:11',ip='10.0.0.11')
        self.h12 = self.net.addHost('h12',mac='00:00:00:00:00:12',ip='10.0.0.12')

        self.s1 = self.net.addSwitch('s1', cls=OVSKernelSwitch)
        self.s2 = self.net.addSwitch('s2', cls=OVSKernelSwitch)
        self.s3 = self.net.addSwitch('s3', cls=OVSKernelSwitch)
        self.s4 = self.net.addSwitch('s4', cls=OVSKernelSwitch)
        self.s5 = self.net.addSwitch('s5', cls=OVSKernelSwitch)
        self.s6 = self.net.addSwitch('s6', cls=OVSKernelSwitch)
        self.s7 = self.net.addSwitch('s7', cls=OVSKernelSwitch)
        self.s8 = self.net.addSwitch('s8', cls=OVSKernelSwitch)
        self.s9 = self.net.addSwitch('s9', cls=OVSKernelSwitch)

        info("*** Link creation\n")

        #connessione host-switch
        self.net.addLink(self.h1, self.s2)
        self.net.addLink(self.h2, self.s1)
        self.net.addLink(self.h3, self.s1)
        self.net.addLink(self.h4, self.s4)
        self.net.addLink(self.h5, self.s3)
        self.net.addLink(self.h6, self.s5)
        self.net.addLink(self.h7, self.s5)
        self.net.addLink(self.h8, self.s6)
        self.net.addLink(self.h9, self.s9)
        self.net.addLink(self.h10, self.s7)
        self.net.addLink(self.h11, self.s7)
        self.net.addLink(self.h12, self.s8)

        #connessione switch-switch
        self.s1_to_s2 = self.net.addLink(self.s1, self.s2)
        self.s2_to_s4 = self.net.addLink(self.s2, self.s4)
        self.s3_to_s4 = self.net.addLink(self.s3, self.s4)
        self.s4_to_s5 = self.net.addLink(self.s4, self.s5)
        self.s4_to_s6 = self.net.addLink(self.s4, self.s6)
        self.s6_to_s7 = self.net.addLink(self.s6, self.s7)
        self.s6_to_s9 = self.net.addLink(self.s6, self.s9)
        self.s7_to_s8 = self.net.addLink(self.s7, self.s8)

        self.list_hosts = [self.h1,self.h2,self.h3,self.h4,self.h5,self.h6,self.h7,self.h8,self.h9,self.h10,self.h11,self.h12]

        #Starting network
        info("*** Starting Network ")
        self.net.build()
        self.net.start()
        

if __name__ == '__main__':

        setLogLevel('info')
        
        info('starting the environment\n')
        env = Environment()
        profiles = TrafficProfiles(env.net)
        env.profiles = profiles

        with open("/tmp/topologia.flag", "w") as f:
            f.write("ok")
                
        # Espone la variabile globale alla CLI
        import builtins
        builtins.env = env
        builtins.profiles = profiles
    
        info("*** Running CLI\n")
        CLI(env.net, script=None)