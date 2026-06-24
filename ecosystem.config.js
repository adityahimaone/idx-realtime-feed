module.exports = {
  apps: [
    {
      name: "idx-realtime-ui",
      script: "/home/adityahimaone/apps/idx-realtime-feed/start_ui.sh",
      cwd: "/home/adityahimaone/apps/idx-realtime-feed",
      env: { NODE_ENV: "production" },
      instances: 1,
      autorestart: true,
      max_restarts: 100
    },
    {
      name: "idx-realtime-alertbot",
      script: "/home/adityahimaone/apps/idx-realtime-feed/.venv/bin/python",
      args: "-m bot.alert_daemon",
      cwd: "/home/adityahimaone/apps/idx-realtime-feed",
      instances: 1,
      autorestart: true,
      max_restarts: 100,
      watch: false,
      merge_logs: true
    }
  ]
};
