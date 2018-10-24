# -*- coding: utf-8 -*-
import tempfile
import threading

import zmq

from lucena.exceptions import AlreadyStarted
from lucena.io2.socket import Socket
from lucena.worker import Worker


class Service(Worker):

    class Controller(object):

        def __init__(self, *args, **kwargs):
            self.context = zmq.Context.instance()
            self.args = args
            self.kwargs = kwargs
            self.poller = zmq.Poller()
            self.thread = None
            self.control_socket = Socket(self.context, zmq.ROUTER)
            self.control_socket.bind(Socket.inproc_unique_endpoint())

        def start(self):
            if self.thread is not None:
                raise AlreadyStarted()
            service = Service(*self.args, **self.kwargs)
            self.thread = threading.Thread(
                target=service.controller_loop,
                daemon=False,
                kwargs={
                    'endpoint': self.control_socket.last_endpoint,
                    'identity': b'service#0'
                }
            )
            self.thread.start()
            _slave_id, client, message = self.control_socket.recv_from_worker()
            assert _slave_id == b'service#0'
            assert client == b'$controller'
            assert message == {"$signal": "ready"}

        def stop(self, timeout=None):
            self.control_socket.send_to_worker(
                b'service#0',
                b'$controller',
                {'$signal': 'stop'}
            )
            _worker_id, client, message = self.control_socket.recv_from_worker()
            assert (_worker_id == b'service#0')
            assert (client == b'$controller')
            assert (message == {'$signal': 'stop', '$rep': 'OK'})
            self.thread.join(timeout=timeout)
            self.thread = None

        def send(self, message):
            # TODO: Raise an error if not started.
            return self.control_socket.send_to_worker(b'service#0', b'$controller', message)

        def recv(self):
            # TODO: Raise an error if not started.
            worker, client, message = self.control_socket.recv_from_worker()
            assert client == b'$controller'
            assert worker == b'service#0'
            return message

    # Service implementation.

    def __init__(self, worker_factory, endpoint=None, number_of_workers=1):
        # http://zguide.zeromq.org/page:all#Getting-the-Context-Right
        # You should create and use exactly one context in your process.
        super(Service, self).__init__()
        self.worker_factory = worker_factory
        self.endpoint = endpoint if endpoint is not None \
            else "ipc://{}.ipc".format(tempfile.NamedTemporaryFile().name)
        self.number_of_workers = number_of_workers

        self.socket = None
        self.worker_controller = None

        self.worker_ready_ids = None
        self.total_client_requests = 0

    def _plug(self, control_socket, number_of_workers):
        # Init worker queues
        self.worker_ready_ids = []
        # Init sockets
        self.socket = Socket(self.context, zmq.ROUTER)
        self.socket.bind(self.endpoint)
        self.control_socket = control_socket
        self.control_socket.signal(Socket.SIGNAL_READY)
        self.worker_controller = Worker.Controller(self.worker_factory)
        self.worker_ready_ids = self.worker_controller.start(number_of_workers)

    def _unplug(self):
        self.socket.close()
        self.control_socket.close()
        self.worker_controller.stop()

    def _handle_poll(self):
        self.poller.register(
            self.control_socket,
            zmq.POLLIN if not self.stop_signal else 0
        )
        self.poller.register(
            self.socket,
            zmq.POLLIN if self.worker_ready_ids and not self.stop_signal else 0
        )
        return dict(self.poller.poll(.1))

    def _handle_socket(self):
        assert len(self.worker_ready_ids) > 0
        client, request = self.socket.recv_from_client()
        worker_name = self.worker_ready_ids.pop(0)
        self.worker_controller.send(worker_name, client, request)
        self.total_client_requests += 1

    def _handle_worker_controller(self):
        worker_id, client, reply = self.worker_controller.recv()
        self.worker_ready_ids.append(worker_id)
        self.socket.send_to_client(client, reply)

    def controller_loop(self, endpoint, identity=None):

        ##
        # Init worker queues
        self.worker_ready_ids = []
        # Init sockets
        self.socket = Socket(self.context, zmq.ROUTER)
        self.socket.bind(self.endpoint)

        self.worker_controller = Worker.Controller(self.worker_factory)
        self.worker_ready_ids = self.worker_controller.start(self.number_of_workers)
        ##

        self.control_socket = Socket(self.context, zmq.REQ, identity=identity)
        self.control_socket.connect(endpoint)
        self.control_socket.send_to_client(b'$controller', {"$signal": "ready"})

        while not self.stop_signal:
            sockets = self._handle_poll()
            if self.control_socket in sockets:
                self._handle_ctrl_socket()
            if self.socket in sockets:
                self._handle_socket()
            if self.worker_controller.message_queued():
                self._handle_worker_controller()

        self._unplug()

    def pending_workers(self):
        return self.worker_ready_ids is not None and \
               len(self.worker_ready_ids) < self.number_of_workers


def create_service(worker_factory=None, endpoint=None, number_of_workers=1):
    return Service.Controller(
        worker_factory,
        endpoint=endpoint,
        number_of_workers=number_of_workers
    )


def main():
    service = create_service(Worker)
    service.start()
    service.send({'$req': 'eval', '$attr': 'total_client_requests'})
    rep = service.recv()
    service.stop()
    print(rep)


if __name__ == '__main__':
    main()
