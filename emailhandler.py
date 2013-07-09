import logging
import logging.handlers


class SMTPHandler(logging.handlers.SMTPHandler):
    # This is a modified version logging.handlers.SMTPHandler.emit

    # Copyright 2001-2010 by Vinay Sajip. All Rights Reserved.
    #
    # Permission to use, copy, modify, and distribute this software and its
    # documentation for any purpose and without fee is hereby granted,
    # provided that the above copyright notice appear in all copies and that
    # both that copyright notice and this permission notice appear in
    # supporting documentation, and that the name of Vinay Sajip
    # not be used in advertising or publicity pertaining to distribution
    # of the software without specific, written prior permission.
    # VINAY SAJIP DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE, INCLUDING
    # ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL
    # VINAY SAJIP BE LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR
    # ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER
    # IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
    # OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

    def emit(self, record):
        """
        Emit a record.

        Format the record and send it to the specified addressees.
        """
        try:
            import smtplib
            from email.utils import formatdate
            port = self.mailport
            if not port:
                if self.secure is not None:
                    port = smtplib.SMTP_SSL_PORT
                else:
                    port = smtplib.SMTP_PORT
            if self.secure is not None:
                smtp = smtplib.SMTP_SSL(self.mailhost, port)
            else:
                smtp = smtplib.SMTP(self.mailhost, port)
            msg = self.format(record)
            msg = "From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\n\r\n%s" % (
                            self.fromaddr,
                            ",".join(self.toaddrs),
                            self.getSubject(record),
                            formatdate(), msg)
            if self.username:
                #if self.secure is not None:
                #    smtp.ehlo()
                #    smtp.starttls(*self.secure)
                #    smtp.ehlo()
                smtp.login(self.username, self.password)
            smtp.sendmail(self.fromaddr, self.toaddrs, msg)
            smtp.quit()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)
