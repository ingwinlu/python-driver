from threading import Lock, RLock

from connection import Connection
from decoder import QueryMessage
from metadata import Metadata
from policies import RoundRobinPolicy, SimpleConvictionPolicy, ExponentialReconnectionPolicy, HostDistance
from query import SimpleStatement

class Session(object):

    def __init__(self, cluster, hosts):
        self.cluster = cluster
        self.hosts = hosts

        self._lock = RLock()
        self._is_shutdown = False
        self._pools = {}
        self._load_balancer = RoundRobinPolicy()

    def execute(self, query):
        if isinstance(query, basestring):
            query = SimpleStatement(query)

    def execute_async(self, query):
        if isinstance(query, basestring):
            query = SimpleStatement(query)

        qmsg = QueryMessage(query=query.query, consistencylevel=query.consistency_level)
        return self._execute_query(qmsg, query)

    def prepare(self, query):
        pass

    def shutdown(self):
        self.cluster.shutdown()

    def _execute_query(self, message, query):
        if query.tracing_enabled:
            # TODO enable tracing on the message
            pass

        errors = {}
        query_plan = self._load_balancer.make_query_plan(query)
        for host in query_plan:
            try:
                result = self._query(host)
                if result:
                    return
            except Exception, exc:
                errors[host] = exc

    def _query(self, host, query):
        pool = self._pools.get(host)
        if not pool or pool.is_shutdown:
            return False

DEFAULT_MIN_REQUESTS = 25
DEFAULT_MAX_REQUESTS = 100

DEFAULT_MIN_CONNECTIONS_PER_LOCAL_HOST = 2
DEFAULT_MAX_CONNECTIONS_PER_LOCAL_HOST = 8

DEFAULT_MIN_CONNECTIONS_PER_REMOTE_HOST = 1
DEFAULT_MAX_CONNECTIONS_PER_REMOTE_HOST = 2

class Cluster(object):

    port = 9042

    auth_provider = None

    load_balancing_policy = None
    reconnecting_policy = None
    retry_policy = None

    compression = None
    metrics_enabled = False
    socket_options = None

    conviction_policy_factory = SimpleConvictionPolicy

    def __init__(self, contact_points):
        self.contact_points = contact_points
        self.sessions = set()
        self.metadata = Metadata(self)

        self._min_requests_per_connection = {
            HostDistance.LOCAL: DEFAULT_MIN_REQUESTS,
            HostDistance.REMOTE: DEFAULT_MIN_REQUESTS
        }

        self._max_requests_per_connection = {
            HostDistance.LOCAL: DEFAULT_MAX_REQUESTS,
            HostDistance.REMOTE: DEFAULT_MAX_REQUESTS
        }

        self._core_connections_per_host = {
            HostDistance.LOCAL: DEFAULT_MIN_CONNECTIONS_PER_LOCAL_HOST,
            HostDistance.REMOTE: DEFAULT_MIN_CONNECTIONS_PER_REMOTE_HOST
        }

        self._max_connections_per_host = {
            HostDistance.LOCAL: DEFAULT_MAX_CONNECTIONS_PER_LOCAL_HOST,
            HostDistance.REMOTE: DEFAULT_MAX_CONNECTIONS_PER_REMOTE_HOST
        }

        # TODO real factory based on config
        self._connection_factory = Connection

        self._is_shutdown = False
        self._lock = Lock()

        self._control_connection = ControlConnection(self, self.metadata)
        try:
            self._control_connection.connect()
        except:
            self.shutdown()
            raise

    def get_min_requests_per_connection(self, host_distance):
        return self._min_requests_per_connection[host_distance]

    def set_min_requests_per_connection(self, host_distance, min_requests):
        self._min_requests_per_connection[host_distance] = min_requests

    def get_max_requests_per_connection(self, host_distance):
        return self._max_requests_per_connection[host_distance]

    def set_max_requests_per_connection(self, host_distance, max_requests):
        self._max_requests_per_connection[host_distance] = max_requests

    def get_core_connections_per_host(self, host_distance):
        return self._core_connections_per_host[host_distance]

    def set_core_connections_per_host(self, host_distance, core_connections):
        old = self._core_connections_per_host[host_distance]
        self._core_connections_per_host[host_distance] = core_connections
        if old < core_connections:
            self.ensure_pool_sizing()

    def get_max_connections_per_host(self, host_distance):
        return self._max_connections_per_host[host_distance]

    def set_max_connections_per_host(self, host_distance, max_connections):
        self._max_connections_per_host[host_distance] = max_connections

    def connect(self, keyspace=None):
        # TODO set keyspace if not None
        return self._new_session()

    def shutdown(self):
        with self._lock:
            if self._is_shutdown:
                return
            else:
                self._is_shutdown = True

        self._control_connection.shutdown()

        for session in self.sessions:
            session.shutdown()

    def _new_session(self):
        session = Session(self, self.metadata.hosts.values())
        self.sessions.add(session)
        return session


class NoHostAvailable(Exception):
    pass


class ControlConnection(object):

    def __init__(self, cluster, metadata):
        self._cluster = cluster
        self._balancing_policy = RoundRobinPolicy()
        self._balancing_policy.populate(cluster, metadata.hosts)
        self._reconnection_policy = ExponentialReconnectionPolicy(2 * 1000, 5 * 60 * 1000)
        self._connection = None

        self._is_shutdown = False

    def connect(self):
        if self._is_shutdown:
            return

    def _reconnect(self):
        errors = {}
        for host in self._balancing_policy:
            try:
                return self._connect_to(host)
            except Exception, exc:
                # TODO logging, catch particular exception types
                errors[host] = exc
                pass

        raise NoHostAvailable("Unable to connect to any servers", errors)

    def _connect_to(self, host):
        # TODO create with cluster connection factory
        # connection = self._cluster.connection_factory.open(host)
        # connection = Connection(host)
        pass

    def shutdown(self):
        self._is_shutdown = True
        if self._connection:
            self._connection.close()

    def refresh_schema(self, keyspace=None, table=None):
        pass

    def refresh_node_list_and_token_map(self):
        pass
