#!/usr/bin/python

import ConfigParser
import socket
import struct
import time
import threading
import logging
import logging.handlers
import smtplib
import cherrypy
from email.utils import COMMASPACE
from email.MIMEText import MIMEText

# Mail notification setup
GMAIL_LOGIN = 'mcast@mobicont.ru'
GMAIL_PASSWORD = 'M22255'
GMAIL_TO_ADDR = ['amalaev@alt-lan.ru']

class UDPChecker:
    def __init__(self):
        config = ConfigParser.SafeConfigParser()
        config.read(['udpchecker.cfg'])
        self.channels = config.items('channels')
        self.notify = config.items('notify')
        self.warnings = {}
        self.times = {}
        self.clist = {}
        # Add some logging
        self.log = logging.getLogger('UDPChecker')
        self.loghandler = logging.handlers.RotatingFileHandler("udpchecker.log", 
                    maxBytes=500000,
                    backupCount=10)
        self.logformat = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        self.loghandler.setFormatter(self.logformat)
        self.log.addHandler(self.loghandler)
        self.log.setLevel(logging.DEBUG)

        # Start to work
        self.work()

    def work(self):
        threads = []
        for [channel,addr] in self.channels:
            self.times[addr] = int(time.time())
            self.clist[addr] = channel
            self.warnings[addr] = 0
            t = self.UDPListener(addr, self)
            threads.append(t)
            t.start()

        try:
            while True:
                for addr in self.times:
                    timeout = int(time.time()) - int(self.times.get(addr))
                    if timeout > 15:
                        self.log.debug("No multicast on %s %s last %s seconds" % (addr, self.clist.get(addr), timeout))
                time.sleep(60)
        except KeyboardInterrupt:
            self.log.debug("Ctrl-c received! Sending kill to threads...")
            for t in threads:
                t.kill_received = True

    def sendWarning(self, addr):
        chan = self.clist.get(addr)
        self.warnings[addr] += 1
        if self.warnings[addr] > 1:
            pass
        else:
            self.log.warning("Timeout, send warning!!! %s %s" % (addr, chan))
            subject = "VIDEON Warning for channel %s" % chan
            msg = "Timeout of multicast receiving on %s for channel %s" % (addr, chan)
            self.sendMail(subject, msg, GMAIL_TO_ADDR)

    def sendMail(self, subject, message, to_addr=GMAIL_TO_ADDR, from_addr=GMAIL_LOGIN):
        msg = MIMEText(message)
        msg['Subject'] = subject
        msg['From'] = from_addr
        msg['To'] = COMMASPACE.join(to_addr)
        server = smtplib.SMTP('smtp.gmail.com',587)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(GMAIL_LOGIN, GMAIL_PASSWORD)
        server.sendmail(from_addr, to_addr, msg.as_string())
        server.close()

    def listenerCb(self, addr):
        chan = self.clist.get(addr)
        self.times[addr] = int(time.time())
        if self.warnings[addr] > 0:
            self.log.warning("Recovery of multicast on %s %s" % (addr, chan))
            subject = "VIDEON Recovery for channel %s" % chan
            msg = "Recovery of multicast receiving on %s for channel %s" % (addr, chan)
            self.sendMail(subject, msg, GMAIL_TO_ADDR)
            self.warnings[addr] = 0


    class UDPListener(threading.Thread):
        def __init__(self, addr, checker):
            self.c = checker
            self.log = self.c.log
            self.addr = addr
            threading.Thread.__init__(self)
            self.kill_received = False

        def run(self):
            self.listen()

        def listen(self):
            udpaddr, udpport = self.addr.split(":")
            self.log.debug("Start listening: %s" % self.addr)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((udpaddr, int(udpport)))
            mreq = struct.pack("4sl", socket.inet_aton(udpaddr), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            while not self.kill_received:
                try:
                        sock.settimeout(5)
                        data, addr = sock.recvfrom( 1024 )
                        self.c.listenerCb(self.addr)
                except socket.timeout:
                        self.c.sendWarning(self.addr)

if __name__ == "__main__":
    UDPChecker()
