from contextmanager import ExitStack
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from unittest.mock import patch


def make_http_server(directory, port):
    """Create an HTTP/S server to vend from the file system.

    :param directory: The file system directory to vend files from.
    :param port: The port to listen on for the server.
    :return: A context manager that when closed, stops the server.
    """
    # We need an HTTP/S server to vend the file system, or at least parts of
    # it, that we want to test.  Since all the files are static, and we're
    # only going to GET files, this makes our lives much easier.  We'll just
    # vend all the files in the directory.
    class RequestHandler(SimpleHTTPRequestHandler):
        # The base class hardcodes the use of os.getcwd() to vend the
        # files from, but we want to be able to pass in any directory.  I
        # suppose we could chdir in the server thread, but let's hack the
        # path instead.
        def translate_path(self, path):
            with patch('http.server.os.getcwd', return_value=directory):
                return super().translate_path(path)

        def log_message(self, *args, **kws):
            # Please shut up.
            pass

        def do_GET(self):
            # If we requested the magic 'user-agent.txt' file, send back the
            # value of the User-Agent header.  Otherwise, vend as normal.
            if self.path == '/user-agent.txt':
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                user_agent = self.headers.get('user-agent', 'no agent')
                self.end_headers()
                self.wfile.write(user_agent.encode('utf-8'))
            else:
                super().do_GET()
    # Create the server in the main thread, but start it in the sub-thread.
    # This lets the main thread call .shutdown() to stop everything.  Return
    # just the shutdown method to the caller.
    RequestHandler.directory = directory
    # Define a small class with a method that arranges for the self-signed
    # certificates to be valid in the client.
    with ExitStack() as stack:
        server = HTTPServer(('localhost', port), RequestHandler)
        server.allow_reuse_address = True
        stack.callback(server.server_close)
        thread = Thread(target=server.serve_forever)
        thread.daemon = True
        def shutdown():
            server.shutdown()
            thread.join()
        stack.callback(shutdown)
        thread.start()
        # Everything succeeded, so transfer the resource management to a new
        # ExitStack().  This way, when the with statement above completes, the
        # server will still be running and urlopen() will still be patched.
        # The caller is responsible for closing the new ExitStack.
        return stack.pop_all()


