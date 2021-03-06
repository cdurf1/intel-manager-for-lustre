{
  "ui_name": "Robinhood Policy Engine Server",
  "managed": true,
  "worker": true,
  "name": "robinhood_server",
  "initial_state": "working",
  "rsyslog": true,
  "ntp": true,
  "corosync": false,
  "corosync2": false,
  "pacemaker": false,
  "bundles": [
    "iml-agent",
    "lustre-client",
    "robinhood"
  ],
  "ui_description": "A server running the Robinhood Policy Engine",
  "packages": {
    "iml-agent": [
      "chroma-agent-management"
    ],
    "lustre-client": [
      "lustre-client-modules",
      "lustre-client"
    ],
    "robinhood": [
      "robinhood-lhsm",
      "robinhood-webgui",
      "robinhood-adm"
    ]
  }
}
