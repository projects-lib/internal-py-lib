# libraries

Internal Python library for XL-Axiata. Provides a Spring Cloud Config Server
loader that fetches properties and returns them as a single flat `dict`, plus a
centralized logging setup.

## Installation

From Git (recommended for teams; pin to a version tag):

```
libraries @ git+https://git-internal/xl-axiata/loader-scc-py.git@v0.1.0
```

Local (single-machine development):

```bash
pip install -e D:\XL-Axiata\RND\RAG\loader-scc-py
```

## Usage

The library reads configuration from environment variables. The consuming
application loads `.env` (e.g. with `python-dotenv`), then:

```python
from dotenv import load_dotenv
from libraries import ConfigServerClient

load_dotenv()                       # load .env into os.environ
remote = ConfigServerClient().fetch()
db_host = remote.get("spring.datasource.host")
```

Or inject values directly without environment variables:

```python
remote = ConfigServerClient(
    uri="http://config-server",
    application="vektor-creator-service",
    profile="sit",
    label="tencent",
).fetch()
```

## Environment variables

| Variable | Role | Default |
|----------|------|---------|
| `SPRING_CLOUD_CONFIG_URI` | Config Server URI | `http://localhost:8888` |
| `APPLICATION_NAME` | application name (URL segment 2) | `application` |
| `SPRING_CLOUD_CONFIG_PROFILE` | profile (URL segment 3) | `default` |
| `LABEL` | label (URL segment 4, optional) | _(empty)_ |
| `SPRING_CLOUD_CONFIG_FAIL_FAST` | `true` raises on failure | `true` |
| `SPRING_CLOUD_CONFIG_REQUEST_TIMEOUT` | timeout in seconds | `10` |

Requested URL: `GET {uri}/{application}/{profile}[/{label}]`

## Centralized logging

The library ships a `LoggingConfigurator` class so every service can set up
consistent logging in one place. It is a **singleton**: constructing it again
returns the same instance, so the whole application shares one central logging
configuration. Like the config client, it reads from environment variables with
defaults and lets you override any setting via constructor arguments.

Call it once at application startup, then obtain loggers anywhere via
`get_logger`:

```python
from dotenv import load_dotenv
from libraries import LoggingConfigurator, get_logger, ConfigServerClient

load_dotenv()
LoggingConfigurator().configure()   # reads LOG_* env vars
log = get_logger(__name__)

remote = ConfigServerClient().fetch()
log.info("configuration loaded", extra={"keys": len(remote)})
```

Override settings directly (mirrors the `ConfigServerClient` style):

```python
LoggingConfigurator(level="DEBUG", fmt="json", stream="stdout").configure()
```

Because it is a singleton, calling it from anywhere returns the same object and
reconfigures logging in place — no duplicate handlers, no competing setups:

```python
LoggingConfigurator(level="DEBUG").configure()   # at startup
# ... elsewhere in the codebase ...
LoggingConfigurator().configure()                # same instance, same config
```

A thin `configure_logging` wrapper is kept for brevity and backwards
compatibility; it delegates to the singleton:

```python
from libraries import configure_logging
configure_logging(level="DEBUG", fmt="json")     # == LoggingConfigurator(...).configure()
```

`configure()` is idempotent — calling it again replaces the handler it installed
instead of stacking duplicates, so it is safe to call at every entry point. With
`fmt="json"`, records are emitted as single-line JSON (including any `extra=`
fields), which is friendly to log aggregators such as ELK, Loki, or CloudWatch.

### Logging environment variables

| Variable | Role | Default |
|----------|------|---------|
| `LOG_LEVEL` | level name (`DEBUG`, `INFO`, ...) or number | `INFO` |
| `LOG_FORMAT` | `plain` or `json` | `plain` |
| `LOG_STREAM` | `stdout` or `stderr` | `stdout` |
| `LOG_DATEFMT` | strftime pattern for timestamps | `%Y-%m-%dT%H:%M:%S%z` |

## Testing

```bash
pip install -e .[test]
pytest
```

## License

MIT
