# Prometheus Toggl Track Exporter Helm Chart

This Helm chart deploys the [Prometheus Toggl Track Exporter](https://github.com/echohello-dev/prometheus-toggl-track-exporter) to a Kubernetes cluster.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+

## Installing the Chart

To install the chart with the release name `toggl-track-exporter`:

```bash
helm install toggl-track-exporter ./deploy/helm/prometheus-toggl-track-exporter \
  --namespace monitoring --create-namespace \
  --set toggl.apiToken="YOUR_TOGGL_API_TOKEN"
```

## Uninstalling the Chart

To uninstall/delete the `toggl-track-exporter` deployment:

```bash
helm uninstall toggl-track-exporter --namespace monitoring
```

## Configuration

The following table lists the configurable parameters of the Prometheus Toggl Track Exporter chart and their default values.

| Parameter                      | Description                                                                 | Default                                                              |
| ------------------------------ | --------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `replicaCount`                 | Number of exporter pods to deploy                                           | `1`                                                                  |
| `image.repository`             | Image repository                                                            | `ghcr.io/echohello-dev/prometheus-toggl-track-exporter`                |
| `image.pullPolicy`             | Image pull policy                                                           | `IfNotPresent`                                                       |
| `image.tag`                    | Overrides the image tag (defaults to chart's `appVersion`)                  | `""`                                                                 |
| `imagePullSecrets`             | List of secrets to use for pulling the image                                | `[]`                                                                 |
| `nameOverride`                 | String to override the default chart name                                   | `""`                                                                 |
| `fullnameOverride`             | String to override the fully qualified chart name                           | `""`                                                                 |
| `serviceAccount.create`        | Specifies whether a service account should be created                       | `true`                                                               |
| `serviceAccount.automount`     | Automatically mount a ServiceAccount token                                  | `true`                                                               |
| `serviceAccount.annotations`   | Annotations to add to the service account                                   | `{}`                                                                 |
| `serviceAccount.name`          | The name of the service account to use                                      | `""` (generated if `create` is true)                               |
| `podAnnotations`               | Annotations to add to the pod                                               | `{}`                                                                 |
| `podLabels`                    | Labels to add to the pod                                                    | `{}`                                                                 |
| `podSecurityContext`           | Security context settings for the pod                                       | `{}`                                                                 |
| `securityContext`              | Security context settings for the container                                 | `{}`                                                                 |
| `service.type`                 | Type of Kubernetes service to create                                        | `ClusterIP`                                                          |
| `service.port`                 | Port the service should expose                                              | `9090`                                                               |
| `service.annotations`          | Annotations to add to the service                                           | `{}`                                                                 |
| `injectSecrets.enabled`        | If true, uses `secretName` to inject `TOGGL_API_TOKEN` as an environment variable | `true`                                                               |
| `injectSecrets.secretName`     | Name of the Kubernetes Secret containing the `TOGGL_API_TOKEN` key            | `"toggl-secret"`                                                     |
| `exporter.port`                | Port the exporter container listens on                                      | `9090`                                                               |
| `exporter.collectionInterval`  | Interval in seconds for collecting metrics                                  | `60`                                                                 |
| `exporter.timeEntriesLookbackHours` | Lookback period in hours for fetching time entries                           | `24`                                                                 |
| `exporter.resources`           | Resource requests and limits for the exporter pod                           | `{}`                                                                 |
| `toggl.apiToken`               | Your Toggl Track API Token (used only if `injectSecrets.enabled` is `false`) | `"YOUR_TOGGL_API_TOKEN"`                                             |
| `serviceMonitor.enabled`       | If true, creates a ServiceMonitor resource for Prometheus Operator          | `false`                                                              |
| `serviceMonitor.namespace`     | Namespace where the ServiceMonitor should be installed                      | (defaults to chart namespace)                                        |
| `serviceMonitor.labels`        | Additional labels for the ServiceMonitor                                    | `{}`                                                                 |
| `serviceMonitor.interval`      | Interval at which metrics should be scraped                                 | `30s`                                                                |
| `serviceMonitor.scrapeTimeout` | Timeout for scraping metrics                                                | `10s`                                                                |
| `nodeSelector`                 | Node labels for pod assignment                                              | `{}`                                                                 |
| `tolerations`                  | Tolerations for pod scheduling                                              | `[]`                                                                 |
| `affinity`                     | Affinity rules for pod scheduling                                           | `{}`                                                                 |

Specify each parameter using the `--set key=value[,key=value]` argument to `helm install`.

Alternatively, a YAML file that specifies the values for the parameters can be provided while installing the chart.
