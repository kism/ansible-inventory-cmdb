"""Run the app with uvicorn."""

import os

import uvicorn


def main() -> None:
    """Serve the app. One worker only, each worker would build its own copy of the CMDB."""
    uvicorn.run(
        "ansibleinventorycmdb:create_app",
        factory=True,
        host=os.environ.get("AIC_HOST", "127.0.0.1"),
        port=int(os.environ.get("AIC_PORT", "5100")),
        log_config=None,  # Our logger config handles uvicorn's loggers
    )


if __name__ == "__main__":
    main()
