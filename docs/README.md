# Hound Documentation

This directory contains operator guides, architecture notes, and reference
contracts that are too detailed for the root README.

## Start Here

- [Root README](../README.md) - installation, commands, and primary usage.
- [Architecture](architecture.md) - pipeline stages, module boundaries, and data flow.
- [Contributing](../CONTRIBUTING.md) - development setup and verification gates.

## Guides

- [GitHub Action](guides/github-action.md)
- [Server deployment](guides/server-deployment.md)
- [Deployment connectors](guides/deployment-connectors.md)

## Reference

- [Log format](reference/log-format.md)
- [Source intelligence](reference/source-intelligence.md)
- [Test impact](reference/test-impact.md)
- [Timeline schema](reference/timeline-schema.md)
- [Schema migration](reference/schema-migration-v1.4-to-v2.0.md)
- [RCA JSON Schema](schema/rca-v2.0.schema.json)

## Operations

- [Dependency policy](operations/dependency-policy.md)
- [Delivery reliability](operations/delivery-reliability.md)
- [Operational correlation](operations/operational-correlation.md)
- [Operations metrics](operations/operations-metrics.md)
- [Server state recovery](operations/state-recovery.md)
- [Threat model](operations/threat-model.md)

## Additional Material

- [Nginx example](examples/nginx-hound.conf)
- [Bounded operation limits](benchmarks/limits.md)
