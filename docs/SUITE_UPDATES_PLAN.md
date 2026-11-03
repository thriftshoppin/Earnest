# Earnest suite updates: design plan

This is a proposal, not an implemented updater. It covers the engine and CLI, Studio, Frankenjack, optional models and the VM lab. Driver updates require their own Windows driver installation and signing workflow; updating a user-space application alone does not install or validate a driver.

## Update contract

- Give each component a version and publish a suite manifest describing compatible component versions, platform, architecture, prerequisites, download sizes and cryptographic hashes. Define the engine API and room/profile schema versions explicitly.
- Keep application files separate from rooms, imported audio, models, presets, configurations, recordings and logs. Upgrades must preserve user data; schema migrations require a backup and a documented rollback strategy.
- Stage updates in a writable temporary directory on the target machine. Verify integrity and publisher authenticity before applying anything; signatures need a trusted key and a defined key rotation and revocation process, not just a hash next to a download.
- Check free space, runtime and driver prerequisites, and component compatibility before switching versions. Report exactly what is blocked. Downloads and installation should be resumable and progress should be visible.
- Install the new version beside the existing version. An external updater coordinates application processes, performs an atomic switch where the platform supports it, runs health checks, and rolls back to the previous version on failure. Never replace files held by a running process in place.
- Keep a local, inspectable update history with versions, outcome and log location. Expose check, download, apply and rollback through both the CLI and the Studio, using the same update engine.
- Offer explicit update channels for development, lab and stable releases. A VM lab should be configurable independently of the host; no production driver or host security settings are changed as a side effect of a VM update.
- Make update timing clear: controls and resources may support hot reload; replacing running binaries or drivers may require a controlled restart. Preserve the user's live audio session until they choose an appropriate time to switch.

## First implementation milestones

1. Inventory existing installers, VM update script, app data locations and current versioning; establish a signed release and manifest format.
2. Build a local-only staged updater and rollback path for user-space components, with tests for interrupted installs, incompatible versions and preserved user data.
3. Add a shared CLI/Studio update view and package building, then separately design authenticated network delivery and driver update handling.
