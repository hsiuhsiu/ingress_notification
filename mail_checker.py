#!/usr/bin/env python3

import sys
import threading
from imaplib2 import imaplib2
import email
from email.header import decode_header
import logging
import pprint

PP = pprint.PrettyPrinter(indent=2)

class MailChecker(threading.Thread):
    lg = None
    waitingEvent = threading.Event()
    imap = None
    username = None
    password = None
    server = None
    old_mails = set()
    raw_mail_handler = None
    kill_now = False
    timeout = 0

    @staticmethod
    def plain_text_from_raw_email(raw_email):
        """
        Extract (to, from, subject, contents) of a given raw_email using
        'email' module. Contents only contains "text/plain" part. Other
        parts will be ignored.
        """
        mail = email.message_from_string(raw_email)

        _to = ''
        _from = ''
        _subject = ''
        _msg = ''

        if mail['To']:
            _to = mail['To']

        if mail['From']:
            _from = mail['From']

        # Extract the subject.
        encoded_subject = mail['Subject']
        if encoded_subject:
            headers = decode_header(encoded_subject)
            # If mutliple encodings are used in subject, the list headers will
            # have many tuples in the form of (text, encode_method).
            for (s, enc) in headers:
                # Encode is not necessary if s is str not bytes
                if isinstance(s, bytes):
                    if enc: # enc could be None
                        s = s.decode(enc)
                    else:
                        s = s.decode()
                _subject += s

        # Extract contents. (only text/plain type).
        for part in mail.walk():
            #lg.debug(part)
            if part.get_content_type() == 'text/plain':
                _msg = part.get_payload(decode=True).decode(part.get_content_charset())
            elif part.get_content_type() == 'text/html':
                _html = part.get_payload(decode=True).decode(part.get_content_charset())

        return (_to, _from, _subject, _msg, _html)

    @staticmethod
    def content_cleanup(msg):
        msg = msg.split('\n')
        new_msg = []
        for m in msg:
            if m not in ['\r', '\n', '']:
                if m[-1] == '\r':
                    m = m[:-1]
                new_msg.append(m)
        return new_msg

    def connect(self):
        self.lg.info('Connecting to the mail server...')
        self.imap = imaplib2.IMAP4_SSL(self.server)
        try:
            typ, data = self.imap.login(self.username, self.password)
            self.imap.select('INBOX')
            typ, data = self.imap.SEARCH(None, 'ALL')
            # If you want to debug, you could comment this line and mark
            # your mail unread.
            #self.old_mails = set(data[0].split())
        except BaseException as e:
            self.lg.error('Could\'t connect to IMAP server: %s.', str(e))
            sys.exit(1)
        self.lg.info('Found %d mails.', len(self.old_mails))

    def __init__(self, username, password,
            server='imap.gmail.com',
            timeout=600,
            raw_mail_handler=lambda *args : None):
        self.lg = logging.getLogger(__name__)
        self.lg.debug('Iniializing MailChecker object.')
        threading.Thread.__init__(self)
        self.server = server
        self.timeout = timeout
        self.username = username
        self.password = password
        self.raw_mail_handler = raw_mail_handler
        self.connect()

    def run(self):
        self.lg.debug('Running MailChecker.')
        while not self.kill_now:
            self.wait_for_new_mail()
        self.lg.debug('Stop running MailChecker.')

    def kill(self):
        self.lg.debug('Killing MailChecker.')
        self.kill_now = True
        self.waitingEvent.set()

    def _get_raw_email_from_fetched_data(self, data):
        for i in range(len(data)):
            if isinstance(data[i], tuple):
                return data[i][1]

    def wait_for_new_mail(self):
        self.lg.debug('Waiting for new mails....')
        self.waitingEvent.clear()
        callback_normal = True
        def _idle_callback(args):
            self.lg.debug("imap.idle callback with args {!r}".format(args))
            try:
                if args[0][1][0] == ('IDLE terminated (Success)'):
                    self.lg.debug('Got a new mail or timeout')
                    self.callback_normal = True
                else:
                    lg.warning('imap.idle callback abnormally')
                    self.callback_normal = False
            except TypeError:
                self.lg.warning('imap.idle callback abnormally')
                self.callback_normal = False
            self.waitingEvent.set()
        try:
            self.imap.idle(timeout=self.timeout, callback=_idle_callback)
            self.waitingEvent.wait()
        except Exception as e:
            self.lg.error('Idle error. Prepare for reconnecting')
            self.connect()
        self.lg.debug('Waiting ended.')
        if self.kill_now:
            self.lg.warning('The thread is killed. Stop waiting.')
            self.imap.CLOSE()
            self.imap.LOGOUT()
        elif self.callback_normal == True:
            typ, data = self.imap.SEARCH(None, 'UNSEEN')
            self.lg.debug('Data: %r', data)
            new_mails = 0
            new_mails = set(data[0].split()) - self.old_mails
            if len(new_mails) == 0:
                self.lg.debug('No new mail.')
            else:
                self.lg.info('Got new mail(s)!')
                for _id in new_mails:
                    self.lg.debug('Mail ID: %r', _id)
                    typ, d = self.imap.fetch(_id, '(RFC822)')
                    self.lg.debug("{0!r}  {1!r}".format(type(d), d))
                    raw_email = self._get_raw_email_from_fetched_data(d)
                    self.lg.debug("{0!r}  {1!r}".format(type(raw_email), d))
                    self.raw_mail_handler(raw_email)


def run(username, password, imap_server='imap.gmail.com', callback=None):

    def handler(raw_email):
        _to, _from, _sub, _msg = MailChecker.plain_text_from_raw_email(raw_email)
        m = MailChecker.content_cleanup(_msg)
        self.lg.debug("to (type={0!r}) {1!r}".format(type(_to), _to))
        self.lg.debug("from (type = {0!r}) {1!r}".format(type(_from), _from))
        self.lg.debug("subject (type = {0!r}) {1!r}".format(type(_sub), _sub))
        self.lg.debug("message = {}".format(PP.pformat(_msg)))
        if callback:
            callback(_from, _to, _sub, m)

    # Start MailChecker
    mail_checker = MailChecker(username, password, imap_server, raw_mail_handler=handler)
    mail_checker.start()
