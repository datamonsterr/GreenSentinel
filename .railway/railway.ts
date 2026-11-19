import { defineRailway, image, preserve, project, redis, service, volume } from "railway/iac";

export default defineRailway(() => {
  const Redis = redis("Redis", { region: "sfo" });
  Redis.deploy = { startCommand: "/bin/sh -c \"rm -rf $RAILWAY_VOLUME_MOUNT_PATH/lost+found/ && exec docker-entrypoint.sh redis-server --requirepass $REDIS_PASSWORD --save 60 1 --dir $RAILWAY_VOLUME_MOUNT_PATH\"" };
  Redis.networking = { privateNetworkEndpoint: "redis", tcpProxies: { "6379": {} } };
  const redisVolume = volume("redis-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "sfo", sizeMB: 500 });
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "sfo", sizeMB: 500 });
  const Postgres = service("Postgres", {
    source: image("postgis/postgis:16-3.4-alpine"),
    replicas: { "sfo": 1 },
    deploy: { requiredMountPath: "/var/lib/postgresql/data" },
    networking: { privateNetworkEndpoint: "postgres", tcpProxies: { "5432": {} } },
    volumeMounts: { "/var/lib/postgresql/data": postgresVolume },
    env: { DATABASE_URL: preserve(), PGDATA: preserve(), PGDATABASE: preserve(), PGHOST: preserve(), PGPASSWORD: preserve(), PGPORT: preserve(), PGUSER: preserve(), POSTGRES_DB: preserve(), POSTGRES_PASSWORD: preserve(), POSTGRES_USER: preserve(), RAILWAY_DEPLOYMENT_DRAINING_SECONDS: preserve(), SSL_CERT_DAYS: preserve() },
  });
  const greensentinelBackend = service("greensentinel-backend", {
    // No source: CI deploys the backend with `railway up` (scripts/railway_deploy_code.sh).
    replicas: { "sfo": 1 },
    env: { APP_ENV: preserve(), CLERK_AUTHORIZED_PARTIES: preserve(), CLERK_ISSUER: preserve(), CLERK_JWKS_URL: preserve(), CLERK_SECRET_KEY: preserve(), CORS_ORIGINS: preserve(), DATABASE_URL: preserve(), GEMINI_API_KEY: preserve(), GEMINI_MODEL: preserve(), LANGCHAIN_API_KEY: preserve(), LANGCHAIN_PROJECT: preserve(), LANGCHAIN_TRACING_V2: preserve(), LLM_MODEL: preserve(), LOG_LEVEL: preserve(), MODEL: preserve(), NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: preserve(), OPENAI_API_KEY: preserve(), OPENROUTER_API_KEY: preserve(), PROJECT_JEV_API_KEY: preserve(), PROJECT_JEV_MODEL: preserve(), QDRANT_CLUSTER_URL: preserve(), QDRANT_DEV_API_KEY: preserve(), QDRANT_PROD_API_KEY: preserve(), QDRANT_TEST_API_KEY: preserve(), REDIS_URL: preserve(), SIMULATION_TENANT_ALLOW: preserve() },
  });

  return project("greensentinel", {
    resources: [Redis, Postgres, greensentinelBackend, redisVolume, postgresVolume],
  });
});
