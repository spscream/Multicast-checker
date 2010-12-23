#!/usr/bin/python

import ConfigParser
import socket
import struct
import time
import threading
import logging
import logging.handlers
import smtplib
import SocketServer
import SimpleHTTPServer
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
        # Set logfile handler
        self.loghandler = logging.handlers.RotatingFileHandler("udpchecker.log",
                                                               maxBytes=500000,
                                                               backupCount=10)
        # Set console handler
        self.consolehandler = logging.StreamHandler()
        self.logformat = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        # Set Formatter to the handlers
        self.loghandler.setFormatter(self.logformat)
        self.consolehandler.setFormatter(self.logformat)
        # Add handlers to the log object
        self.log.addHandler(self.consolehandler)
        self.log.addHandler(self.loghandler)
        # set logging verbosity
        self.log.setLevel(logging.DEBUG)

        # Start to work
        self.work()

    def work(self):
        threads = []
        for [channel, addr] in self.channels:
            self.times[addr] = int(time.time())
            self.clist[addr] = channel
            self.warnings[addr] = 0
            t = UDPListener(addr, self)
            threads.append(t)
            t.start()

        # Start Notify Thread
        notifier = UDPNotifier(self)
        threads.append(notifier)
        notifier.start()

        # Start Monitor Thread
        monitor = UDPHttpMonitor(self)
        threads.append(monitor)
        monitor.start()

        try:
            while True:
                for addr in self.times:
                    timeout = int(time.time()) - int(self.times.get(addr))
                    if timeout > 60:
                        self.log.debug("No multicast on %s %s last %s seconds" % (addr, self.clist.get(addr), timeout))
                time.sleep(60)
        except KeyboardInterrupt:
            self.log.debug("Ctrl-c received! Sending kill to threads...")
            for t in threads:
                t.shutdown()

    def sendWarning(self, addr):
        chan = self.clist.get(addr)
        self.warnings[addr] += 1
        if self.warnings[addr] > 1:
            pass
        else:
            self.log.warning("Timeout, send warning!!! %s %s" % (addr, chan))
            subject = "VIDEON Warning for channel %s" % chan
            msg = "Timeout of multicast receiving on %s for channel %s" % (addr, chan)
            #self.sendMail(subject, msg, GMAIL_TO_ADDR)

    def setWarning(self, addr):
        chan = self.clist.get(addr)
        self.warnings[addr] += 1

    def sendMail(self, subject, message, to_addr=GMAIL_TO_ADDR, from_addr=GMAIL_LOGIN):
        msg = MIMEText(message)
        msg['Subject'] = subject
        msg['From'] = from_addr
        msg['To'] = COMMASPACE.join(to_addr)
        server = smtplib.SMTP('smtp.gmail.com', 587)
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
            self.warnings[addr] = 0

class UDPCheckerThread(threading.Thread):
    def __init__(self, checker):
        self.c = checker
        self.log = self.c.log
        threading.Thread.__init__(self)
        self.kill_received = False

    def run(self):
        self.log.debug("Thread %s started" % self.__class__.__name__)
        while not self.kill_received:
            self.work()
        self.log.debug("Thread %s stopped" % self.__class__.__name__)

    def work(self):
        pass

    def shutdown(self):
        self.kill_received = True

class UDPListener(UDPCheckerThread):
    def __init__(self, addr, checker):
        self.addr = addr
        self.chan = checker.clist.get(addr)
        UDPCheckerThread.__init__(self, checker)

    def work(self):
        self.listen()

    def listen(self):
        udpaddr, udpport = self.addr.split(":")
        #self.log.debug("Start listening: %s" % self.addr)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((udpaddr, int(udpport)))
        mreq = struct.pack("4sl", socket.inet_aton(udpaddr), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        while not self.kill_received:
            try:
                sock.settimeout(5)
                data, addr = sock.recvfrom(1024)
                self.c.listenerCb(self.addr)
            except socket.timeout:
                self.c.setWarning(self.addr)
                self.log.debug("Socket timeout on %s %s" % (self.addr, self.chan))


class UDPHttpMonitor(UDPCheckerThread):
    def __init__(self, checker):
        PORT = 8008
        self.handler = SimpleHTTPServer.SimpleHTTPRequestHandler
        self.httpd = SocketServer.TCPServer(("", PORT), self.handler)
        UDPCheckerThread.__init__(self, checker)

    def work(self):
        self.httpd.handle_request()

    def shutdown(self):
        self.kill_received = True
        self.httpd.server_close()

class UDPNotifier(UDPCheckerThread):
    def work(self):
        self.gen_html()
        time.sleep(5)


    def gen_html(self):
        self.channel_list = ""
        self.output_html = "<html>\r\n"\
                           "<head><title>Channel Monitoring</title></head>\r\n"\
                           "<body>\r\n<table>\r\n"
        for i in self.c.warnings:
            status = self.c.warnings.get(i)
            channel = self.c.clist.get(i)
            if status > 0:
                self.channel_list += "<tr><td>%s</td><td>ERROR</td></tr>" % channel
            else:
                self.channel_list += "<tr><td>%s</td><td>PLAY</td></tr>" % channel
        self.output_html += self.channel_list
        self.output_html += "</table>\r\n</body>\r\n</html>\r\n"
        f = open('index.html', 'w')
        f.write(self.output_html)
        f.close()


if __name__ == "__main__":
    UDPChecker()
