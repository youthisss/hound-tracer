from pathlib import Path


def test_nginx_example_enforces_server_boundary():
    config = Path("docs/examples/nginx-hound.conf").read_text(encoding="utf-8")
    for directive in (
        "listen 443 ssl",
        "client_max_body_size 1m",
        "limit_req_zone",
        "limit_req zone=hound_per_client",
        "proxy_set_header Authorization $http_authorization",
        "proxy_pass http://127.0.0.1:8123",
    ):
        assert directive in config
    access_format = next(line for line in config.splitlines() if "log_format hound_safe" in line)
    assert "$http_authorization" not in access_format
    assert "$request_uri" not in access_format
