## Overview

Basically, this is a unified endpoint for all the browsergym workers. Start the server, and use the entrypoint client to send tasks to workers.

## Install

First we need to setup the dependencies: BrowserGym. We use a forked version of BrowserGym that support asyncio.

```shell
git clone https://github.com/thwu1/BrowserGym.git
cd BrowserGym
make async
```

Then we can install dependencies for the proxy server.

```shell
uv pip install -r requirements.txt
uv pip install -e .
```

## Start the server

First, configure the environment variables needed for the BrowserGym workers. Replace your openai key in `env_var.sh`.

Then start the proxy app with uvicorn.

```shell
cd browser_pilot
source env_var.sh
cd browser_pilot
uvicorn proxy:app --host 0.0.0.0 --port <port> --workers 8 --loop uvloop --ws-max-size 10000000
```