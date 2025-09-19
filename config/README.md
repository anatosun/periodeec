# Configuration Directory

Place your `config.yaml` file in this directory for Docker deployment.

## Quick Setup

```bash
# Copy the example configuration
cp ../config.example.yaml config.yaml

# Edit with your settings
nano config.yaml
```

## Docker Volume Mount

This directory is mounted to `/config` in the Docker container:
- Host: `./config/config.yaml`
- Container: `/config/config.yaml`

The application will automatically detect the configuration file through the `PERIODEEC_CONFIG` environment variable.