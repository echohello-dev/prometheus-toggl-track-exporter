# Prometheus Toggl Track Exporter

Extract Toggl Track API metrics via Prometheus with this exporter.

> [!IMPORTANT]
> This project is not affiliated with Toggl Track. It is a community-driven project.

## Features

- Collects metrics from the Toggl Track API v9 using the `requests` library
- Exposes these metrics in Prometheus format
- Tracks currently running time entries
- Configurable through environment variables
- Includes Docker support for easy deployment
- Uses Poetry for dependency management
- Includes Taskfile for command orchestration
- Manages tool versions with asdf
- Uses Ruff for lightning-fast Python linting and formatting

## Metrics

The exporter currently provides the following metrics:

| Metric                             | Description                                                        | Labels                                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `toggl_time_entry_running`         | Indicates if a time entry is currently running (1=running, 0=stopped) | workspace_id, project_id, project_name, task_id, task_name, description, tags, billable                    |
| `toggl_time_entry_start_timestamp` | Start time of the current running time entry (Unix timestamp)      | workspace_id, project_id, project_name, task_id, task_name, description, tags, billable                    |
| `toggl_api_errors`                 | Number of Toggl API errors encountered                             | endpoint                                                                                                   |
| `toggl_scrape_duration_seconds`  | Time taken to collect Toggl metrics                                | -                                                                                                          |

*More metrics (e.g., total projects, clients, tags) might be added in the future.*

## Configuration

The exporter can be configured using environment variables:

| Variable              | Description                         | Default |
| --------------------- | ----------------------------------- | ------- |
| `TOGGL_API_TOKEN`     | Toggl Track API token (required)    | -       |
| `EXPORTER_PORT`       | Port for the HTTP server          | 9090    |
| `COLLECTION_INTERVAL` | Seconds between metric collections | 60      |

## Installation

### Using Docker

Pull the latest image from GitHub Container Registry:

```bash
docker pull ghcr.io/echohello-dev/prometheus-toggl-track-exporter:latest
```

Run the exporter:

```bash
docker run -p 9090:9090 -e TOGGL_API_TOKEN=your_api_token ghcr.io/echohello-dev/prometheus-toggl-track-exporter:latest
```

### Using Docker Compose

The `compose.yaml` file sets up the Toggl Track exporter, a Prometheus instance, and a Grafana instance for visualization.

1.  Copy the example environment file and edit it with your API token:

    ```bash
    cp .env.example .env
    # Edit .env with your Toggl Track API token
    ```

2.  Then start the services:

    ```bash
    docker compose up -d # Or use 'task docker-compose-up'
    ```

This will start:
- The **Toggl Track exporter** (port `9090`)
- **Prometheus** (port `9091`), pre-configured to scrape the exporter.
- **Grafana** (port `3000`), pre-configured with Prometheus as a data source and a default Toggl Track dashboard. Credentials are `admin / admin`.

Access Grafana at `http://localhost:3000` to view your metrics.

### Using Poetry

1.  Install Poetry (if not already installed):
    ```bash
    curl -sSL https://install.python-poetry.org | python3 -
    ```

2.  Install the package:
    ```bash
    poetry add prometheus-toggl-track-exporter
    ```

3.  Set up your environment variables:
    ```bash
    cp .env.example .env
    # Edit .env with your Toggl Track API token
    ```

4.  Run the exporter:
    ```bash
    source .env && poetry run toggl-track-exporter
    ```

## Local Development

### Quick Start

1.  Clone the repository:
    ```bash
    git clone https://github.com/echohello-dev/prometheus-toggl-track-exporter.git
    cd prometheus-toggl-track-exporter
    ```

2.  Set up development environment:
    ```bash
    task setup-dev
    ```

    This will:
    - Copy `.env.example` to `.env` (if it doesn't exist)
    - Install dependencies via Poetry
    - Install pre-commit hooks

3.  Edit the `.env` file with your Toggl Track API token:
    ```bash
    # Edit .env with your preferred editor
    nano .env
    ```

4.  Run the exporter:
    ```bash
    source .env && task run
    ```

### Using asdf for tool version management

This project uses [asdf](https://asdf-vm.com/) to manage tool versions (Python, Poetry, Task).

1.  Install asdf following the [installation instructions](https://asdf-vm.com/guide/getting-started.html).

2.  Clone the repository:
    ```bash
    git clone https://github.com/echohello-dev/prometheus-toggl-track-exporter.git
    cd prometheus-toggl-track-exporter
    ```

3.  Install the required tools with asdf:
    ```bash
    task setup
    ```

    This will install the correct versions of Python, Poetry, and Task as specified in `.tool-versions`, and set up your development environment.

4.  Run the exporter:
    ```bash
    source .env && task run
    ```

5.  Run tests:
    ```bash
    task test
    ```

## Pre-commit Hooks

This project uses pre-commit to enforce code quality and standards. The hooks ensure that all code commits meet the project's requirements.

To install the pre-commit hooks:

```bash
task pre-commit-install
```

To manually run the pre-commit checks:

```bash
task pre-commit-run
```

The following checks are included:
- Code formatting with Ruff
- Linting with Ruff
- Basic file checks (trailing whitespace, YAML validation, etc.)
- Poetry configuration verification
- Running tests

## Using Taskfile

This project includes a Taskfile for easy command orchestration. You need to have [Task](https://taskfile.dev/installation/) installed, or you can use the version installed by asdf.

Available tasks (refer to `Taskfile.yml` for the full list):

```bash
# Set up local development environment
task setup-dev

# Set up asdf with all required tools
task setup

# Install dependencies
task install

# Format the code
task format

# Run linting
task lint

# Run tests
task test

# Run the exporter
task run

# Install pre-commit hooks
task pre-commit-install

# Run pre-commit checks
task pre-commit-run

# Build Docker image
task docker-build

# Run Docker container
task docker-run

# Start services with docker-compose
task docker-compose-up

# Run all quality checks (format, lint, test)
task all
```

## Building from Source

1.  Clone the repository:
    ```bash
    git clone https://github.com/echohello-dev/prometheus-toggl-track-exporter.git
    cd prometheus-toggl-track-exporter
    ```

2.  Install tools and dependencies (requires asdf):
    ```bash
    task setup
    task install
    ```

3.  Build the Docker image:
    ```bash
    task docker-build
    ```

## License

This project is licensed under the MIT License.

## GitHub Workflow Setup

This repository uses GitHub Actions workflows for continuous integration, release management, and container publishing.

### Workflow Overview

1.  **CI Workflow** (`ci.yml`)
    - Runs linting and tests for every push and pull request.

2.  **Release Please Workflow** (`release-please.yml`)
    - Automates versioning and release creation.
    - Creates a PR with version bump and changelog updates.
    - When merged, creates a GitHub release with appropriate tags.

3.  **PyPI Publish Workflow** (`publish-pypi.yml`)
    - Triggered when Release Please creates a new release.
    - Builds and publishes the Python package to PyPI.

4.  **Docker Publish Workflow** (`docker-publish.yml`)
    - Builds and tests the Docker image.
    - Publishes the image to GitHub Container Registry (`ghcr.io`).
    - Tags the image appropriately (latest, version, SHA).

### Required Secrets

- `POETRY_PYPI_TOKEN_PYPI`: A PyPI API token for publishing.

### Development to Production Workflow

1.  **Local Development**: Edit `.env`, run `task setup-dev`, code, `source .env && task run`.
2.  **Submit Changes**: Create PR, CI runs.
3.  **Release Process**: Merge PR, Release Please creates release PR. Merge release PR -> GitHub Release, PyPI Publish, Docker Publish.
4.  **Using Released Version**: `docker pull ghcr.io/echohello-dev/prometheus-toggl-track-exporter:latest` or use `docker-compose up -d`.
