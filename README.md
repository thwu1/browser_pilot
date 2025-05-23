## Overview

Basically, this is a unified endpoint for all the browsergym workers. Start the server, and use the entrypoint client to send tasks to workers.

## Install

```shell
pip install -r requirements.txt
pip install -e .
```

## Start the server

In a new terminal, start the app using uvicorn.

```shell
cd browser_pilot
uvicorn proxy:app --host 0.0.0.0 --port <port> --workers 8 --loop uvloop --ws-max-size 10000000
```