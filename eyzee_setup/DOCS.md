# Preparing your EyZEE Home

Connect your EyZEE Zigbee gateway to Ethernet and power it on. Open EyZEE Setup and press **Prepare My Home**. Setup saves a recovery copy, prepares your home services, and checks the connection. Home Assistant restarts during preparation; keep the screen open.

Choose your gateway when prompted. Its MAC address is the stable identifier; its network address may change. When setup passes its checks, choose **Open EyZEE Home**.

If preparation stops, check power and network, then press **Retry Preparation**. If you restarted the Setup app or Home Assistant OS, reopen this screen and press **Prepare My Home**. Your progress is saved.

If the problem repeats, select **Setup progress & help**, download the setup report, and give it to EyZEE Support. Do not send passwords or Zigbee network keys.

This is a test release for a fresh installation. Existing or modified EyZEE files may require installer review before preparation can proceed.

## Optional home address (beta.5)

After preparation succeeds, choose **Use eyzee-home.local** to change the system hostname. This is an explicit choice, never an automatic change. Existing systems retain their hostname unless the owner selects this action; this beta remains for fresh HAOS testing only.

The installer reads the hostname back before offering **Open at New Address**. On an HTTP port-80 installation this opens http://eyzee-home.local/eyzee-main-menu/home. The link preserves the current browser protocol and port, including :8123 when used. It does not change HTTP ports, proxy settings, TLS certificates, or IP configuration. HTTPS installations need a certificate valid for the new name. Local name resolution depends on the client/network; read-back verification is not proof that every client can resolve the address.

Keep the current IP address available before selecting the new name. Old hostname bookmarks may stop working; IP-based access remains available. Avoid using the same hostname as another system on the network. If the new link fails, use the current IP address and review Settings → System → Network. Setup does not force a reboot or redirect the current browser session.

Acceptance: on fresh HAOS, first verify that completing preparation alone leaves the hostname unchanged. Choose the address button, confirm the hostname in HA settings, then open the new address from a separate browser/device and verify EyZEE Home. Verify IP access and persistence after a planned reboot. Check normal HTTP/port-80 access and any nonstandard-port deployment separately. Simulated tests cannot validate mDNS or TLS.

## Room-addition fix (beta.5)

Includes the supplied integration fix for adding standard rooms without replacing
existing indoor/custom rooms. Repeated room types receive unused numbered IDs.
Outdoor areas continue to follow their selected toggles. On fresh HAOS, verify
that adding rooms retains prior room names and device assignments.
