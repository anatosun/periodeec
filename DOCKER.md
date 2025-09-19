# Docker Deployment Guide

This guide covers the improved Docker setup for Periodeec with security best practices, multi-stage builds, and comprehensive container orchestration.

## Quick Start

1. **Copy environment configuration:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

2. **Create configuration directory:**
   ```bash
   mkdir -p config music downloads failed
   cp config.example.yaml config/config.yaml
   # Edit config/config.yaml with your settings
   ```

   **Note:** The Docker setup expects the config file to be at `./config/config.yaml` (inside a config directory), not in the project root.

3. **Build and run:**
   ```bash
   docker-compose -f docker-compose.improved.yml up -d
   ```

## Dockerfile Improvements

### Multi-Stage Build
- **Builder stage**: Contains all build dependencies and compilation tools
- **Production stage**: Minimal runtime image with only necessary components
- **Result**: ~60% smaller final image size

### Security Enhancements
- **Non-root user**: Application runs as unprivileged user
- **Read-only filesystem**: Container root filesystem is read-only
- **No new privileges**: Prevents privilege escalation
- **Minimal attack surface**: Only essential packages in final image

### Performance Optimizations
- **Layer caching**: Requirements copied separately for better cache utilization
- **Virtual environment**: Isolated Python dependencies
- **Tmpfs mounts**: In-memory temporary directories for better I/O performance

### Health Monitoring
- **Health check**: Validates configuration loading
- **Signal handling**: Proper SIGTERM handling for graceful shutdown
- **Resource limits**: Configurable CPU and memory constraints

## Docker Compose Features

### Command Line Arguments

The Periodeec application supports several command-line arguments that can be used with Docker:

| Argument | Description | Docker Usage |
|----------|-------------|--------------|
| `--run` | Continuous scheduled mode (default) | `docker run ... periodeec:latest --run` |
| `--once` | Run sync once and exit | `docker run --rm ... periodeec:latest --once` |
| `--status` | Show status and exit | `docker run --rm ... periodeec:latest --status` |
| `--validate-config` | Validate configuration and exit | `docker run --rm ... periodeec:latest --validate-config` |
| `--config-example` | Generate example config | `docker run --rm ... periodeec:latest --config-example` |
| `--config /path` | Custom config path | Mounted volume path |
| `--log-level LEVEL` | Override log level | `docker run ... periodeec:latest --run --log-level DEBUG` |

### Service Profiles
Enable optional services using profiles:

```bash
# Run with Plex included
COMPOSE_PROFILES=plex docker-compose -f docker-compose.improved.yml up -d

# Run with all downloaders
COMPOSE_PROFILES=downloaders docker-compose -f docker-compose.improved.yml up -d

# Run with all services
COMPOSE_PROFILES=plex,downloaders docker-compose -f docker-compose.improved.yml up -d
```

### Volume Management
- **Named volumes**: For persistent data that doesn't need host access
- **Bind mounts**: For configuration and music files
- **Tmpfs**: For temporary cache data

### Network Isolation
- **Custom network**: Isolated container communication
- **Service discovery**: Containers can communicate by service name

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PUID` | 1000 | User ID for file permissions |
| `PGID` | 1000 | Group ID for file permissions |
| `TZ` | UTC | Timezone for container |
| `LOG_LEVEL` | INFO | Application log level |
| `PLEX_CLAIM` | - | Plex server claim token |

### Volume Mappings

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `./config` | `/config` | Configuration files (read-only) |
| `./music` | `/data/music` | Music library |
| `./downloads` | `/data/downloads` | Download staging |
| `./failed` | `/data/failed` | Failed downloads |
| `cache_data` | `/cache` | Application cache |

## Usage Examples

### Scheduled Mode (Default)
```bash
# Start Periodeec in continuous scheduled mode
docker-compose up -d

# Or explicitly specify scheduled mode
docker run -d --name periodeec \
  -v ./config:/config:ro \
  -v ./music:/data/music \
  ghcr.io/anatosun/periodeec:latest --run
```

### One-Time Sync
```bash
# Run sync once and exit
COMPOSE_PROFILES=once docker-compose up periodeec-once

# Or with docker run
docker run --rm \
  -v ./config:/config:ro \
  -v ./music:/data/music \
  ghcr.io/anatosun/periodeec:latest --once
```

### Status Check
```bash
# Check current status
COMPOSE_PROFILES=status docker-compose up periodeec-status

# Or with docker run
docker run --rm \
  -v ./config:/config:ro \
  -v ./music:/data/music:ro \
  ghcr.io/anatosun/periodeec:latest --status
```

### Configuration Validation
```bash
# Validate configuration
docker run --rm \
  -v ./config:/config:ro \
  ghcr.io/anatosun/periodeec:latest --validate-config
```

### Full Stack Deployment
```bash
# Start with Plex and download services
COMPOSE_PROFILES=plex,downloaders docker-compose up -d
```

### Development Mode
```bash
# Build with development target
docker build --target builder -t periodeec:dev -f Dockerfile.improved .

# Run with local source mounted
docker run -it --rm \
  -v $(pwd):/app \
  -v ./config:/config \
  periodeec:dev bash
```

## Monitoring and Logs

### Health Checks
```bash
# Check service health
docker-compose -f docker-compose.improved.yml ps

# View health check logs
docker inspect periodeec --format='{{.State.Health.Status}}'
```

### Log Management
```bash
# View logs
docker-compose -f docker-compose.improved.yml logs -f periodeec

# Log rotation is automatically configured (10MB max, 3 files)
docker logs periodeec --since 1h
```

### Resource Monitoring
```bash
# Monitor resource usage
docker stats periodeec

# Set custom resource limits in docker-compose.improved.yml
```

## Troubleshooting

### Permission Issues
```bash
# Fix file permissions
sudo chown -R $PUID:$PGID ./music ./downloads ./failed

# Check container user
docker exec periodeec id
```

### Configuration Validation
```bash
# Validate configuration
docker exec periodeec python -m periodeec.main --validate-config

# Check if config file is accessible in container
docker exec periodeec ls -la /config/

# Test config loading
docker exec periodeec python -c "from periodeec.config import load_config; load_config('/config/config.yaml'); print('Config OK')"

# Check environment variables
docker exec periodeec env | grep PERIODEEC
```

**Common Config Issues:**
- **File not found**: Ensure `./config/config.yaml` exists on host (not `./config.yaml`)
- **Permission denied**: Check file permissions with `ls -la config/`
- **Mount path**: Verify Docker Compose volume mount `./config:/config:ro`

### Cache Issues
```bash
# Clear application cache
docker exec periodeec rm -rf /cache/*

# Restart with fresh cache volume
docker-compose -f docker-compose.improved.yml down -v
docker-compose -f docker-compose.improved.yml up -d
```

## Security Considerations

### File Permissions
- Container runs as non-root user
- Host directories should be owned by PUID:PGID
- Configuration files are mounted read-only

### Network Security
- Services communicate on isolated bridge network
- Only necessary ports are exposed
- Consider using a reverse proxy for web interfaces

### Secrets Management
- Store API keys in environment files (not in images)
- Use Docker secrets for production deployments
- Regularly rotate credentials

## Production Deployment

### Docker Swarm
```bash
# Deploy to swarm
docker stack deploy -c docker-compose.improved.yml periodeec
```

### Kubernetes
```bash
# Convert compose to k8s manifests
kompose convert -f docker-compose.improved.yml
```

### CI/CD Integration
```bash
# Build multi-architecture images
docker buildx build --platform linux/amd64,linux/arm64 \
  -t periodeec:latest -f Dockerfile.improved .
```

## Migration from Old Docker Setup

1. **Backup existing data:**
   ```bash
   docker-compose down
   cp -r music music.backup
   cp -r config config.backup
   ```

2. **Update configuration:**
   ```bash
   cp .env.example .env
   # Update .env with your settings
   ```

3. **Deploy improved setup:**
   ```bash
   docker-compose -f docker-compose.improved.yml up -d
   ```

4. **Verify data integrity:**
   ```bash
   docker exec periodeec python -m periodeec.main --status
   ```