import os
import socket
import threading

import zmq

class ZMQLockClient(object):

    RESPONSE_TIMEOUT = 2000
    
    def __init__(self, host, port):
        self.host = socket.gethostbyname(host)
        self.port = port
        self.lock = threading.Lock()
        # We'll store one zmq socket/poller for each thread, wit thread local storage:
        self.local = threading.local()
        
    def new_socket(self):
        # Every time the REQ/REP cadence is broken, we need to create
        # and bind a new socket to get it back on track. Also, we have
        # a separate socket for each thread:
        context = zmq.Context.instance()
        self.local.sock = context.socket(zmq.REQ)
        self.local.sock.setsockopt(zmq.LINGER, 0)
        self.local.poller = zmq.Poller()
        self.local.poller.register(self.local.sock, zmq.POLLIN)
        self.local.sock.connect('tcp://%s:%s'%(self.host, str(self.port)))    
        self.local.uuid = self.uuid()
    
    def uuid(self):
        host_name = socket.gethostname()
        process_id = str(os.getpid())
        thread_name= threading.current_thread().name
        return ':'.join([host_name,process_id,thread_name])
    
    def say_hello(self):
        """Ping the server to test for a response"""
        if not hasattr(self.local,'sock'):
            self.new_socket()
        self.local.sock.send('hello')
        events = self.local.poller.poll(self.RESPONSE_TIMEOUT)
        if events:
            response = self.local.sock.recv()
            if response == 'hello':
                return
        del self.local.sock
        raise zmq.ZMQError('No response from server: timed out')
        
    def acquire(self, key, timeout):
        if not hasattr(self.local,'sock'):
            self.new_socket()
        while True:
            messages = ['acquire',str(key),self.uuid(), str(timeout)]
            self.local.sock.send_multipart(messages)
            events = self.local.poller.poll(self.RESPONSE_TIMEOUT)
            if not events:
                del self.local.sock
                raise zmq.ZMQError('No response from server: timed out')
            else:    
                signal, data = self.local.sock.recv_multipart()
                if signal == 'error':
                    raise zmq.ZMQError(data)
                elif signal == 'retry':
                    continue
                elif signal == 'ok':
                    break
        
    def release(self, key):
        if not hasattr(self.local,'sock'):
            self.new_socket()
        messages = ['release',str(key),self.uuid()]
        self.local.sock.send_multipart(messages)
        events = self.local.poller.poll(self.RESPONSE_TIMEOUT)
        if not events:
            del self.local.sock
            raise zmq.ZMQError('No response from server: timed out')
        else:    
            signal, data = self.local.sock.recv_multipart()
            if signal == 'error':
                raise zmq.ZMQError(data)
            elif signal == 'ok':
                return


def acquire(key, timeout):
    """Acquire a lock identified by key, for a specified time in
    seconds. Blocks until success, raises exception if the server isn't
    responding"""
    try:
        _zmq_lock_client.acquire(key, timeout)
    except NameError:
        raise RuntimeError('Not connected to a zlock server')
        
def release(key):
    """Release the lock identified by key. Raises an exception if the
    lock was not held, or was held by someone else, or if the server
    isn't responding"""
    try:
        _zmq_lock_client.release(key)
    except NameError:
        raise RuntimeError('Not connected to a zlock server')
        
def connect(host='localhost', port=7339):
    """This method should be called at program startup, it establishes
    communication with the server and ensures it is responding"""
    global _zmq_lock_client                 
    _zmq_lock_client = ZMQLockClient(host, port)
    _zmq_lock_client.say_hello()
    
