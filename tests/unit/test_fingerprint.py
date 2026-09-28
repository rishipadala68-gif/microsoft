from app.core.fingerprint import fingerprints, parse_stack_trace


def test_fingerprints_identical_with_different_lines_and_uuids():
    trace1 = """
Traceback (most recent call last):
  File "/app/services/checkout.py", line 45, in process_order
  File "/app/clients/db.py", line 120, in get_connection
ConnectionError: Failed connection for 123e4567-e89b-12d3-a456-426614174000
    """

    trace2 = """
Traceback (most recent call last):
  File "/app/services/checkout.py", line 98, in process_order
  File "/app/clients/db.py", line 250, in get_connection
ConnectionError: Failed connection for 987f6543-e21a-45c3-b789-123456789abc
    """

    fps1 = fingerprints(trace1)
    fps2 = fingerprints(trace2)
    assert len(fps1) > 0
    assert len(fps2) > 0
    assert fps1[0] == fps2[0]


def test_fingerprints_differ_for_different_app_frames():
    trace1 = """
Traceback (most recent call last):
  File "/app/services/checkout.py", line 45, in process_order
  File "/app/clients/db.py", line 120, in get_connection
ConnectionError: HikariPool connection timeout
    """

    trace2 = """
Traceback (most recent call last):
  File "/app/services/checkout.py", line 45, in process_order
  File "/app/clients/redis_cache.py", line 55, in fetch_key
ConnectionError: Redis connection timeout
    """

    fps1 = fingerprints(trace1)
    fps2 = fingerprints(trace2)
    assert fps1[0] != fps2[0]


def test_java_stack_trace_parsing():
    trace = """
Exception in thread "main" java.lang.NullPointerException: Cannot invoke method
\tat com.acme.orders.OrderService.createOrder(OrderService.java:42)
\tat com.acme.orders.OrderController.handlePost(OrderController.java:88)
\tat org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1064)
    """
    exc_type, frames = parse_stack_trace(trace)
    assert exc_type == "NullPointerException"
    app_frames = [f for f in frames if f.is_app]
    assert len(app_frames) == 2
    assert app_frames[0].function == "createOrder"
