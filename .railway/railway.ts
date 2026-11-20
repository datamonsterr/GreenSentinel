import { defineRailway, github, image, preserve, project, redis, service, volume } from "railway/iac";

export default defineRailway(() => {
  const Redis = redis("Redis", { region: "sfo" });
  Redis.deploy = { multiRegionConfig: { sfo: { numReplicas: 1 } }, startCommand: "/bin/sh -c \"rm -rf $RAILWAY_VOLUME_MOUNT_PATH/lost+found/ && exec docker-entrypoint.sh redis-server --requirepass $REDIS_PASSWORD --save 60 1 --dir $RAILWAY_VOLUME_MOUNT_PATH\"" };
  Redis.networking = { privateNetworkEndpoint: "redis" };
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "sfo", sizeMB: 5000 });
  const redisVolume = volume("redis-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "sfo", sizeMB: 5000 });
  const greensentinelBackend = service("greensentinel-backend", {
    source: github("datamonsterr/GreenSentinel", { branch: "main", checkSuites: true }),
    build: { buildEnvironment: "V3", builder: "RAILPACK", watchPatterns: ["src/**", "!src/webapp/**", "Dockerfile", ".dockerignore", "requirements.txt", "models/**", "config/**", "db/**", "scripts/**"] },
    healthcheck: "/health",
    healthcheckTimeout: 300,
    replicas: { "sfo": 1 },
    deploy: { sleepApplication: true },
    env: { APP_ENV: preserve(), CLERK_AUTHORIZED_PARTIES: preserve(), CLERK_ISSUER: preserve(), CLERK_JWKS_URL: preserve(), CLERK_SECRET_KEY: preserve(), CORS_ORIGINS: preserve(), DATABASE_URL: preserve(), LLM_MODEL: preserve(), LOG_LEVEL: preserve(), NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: preserve(), OPENROUTER_API_KEY: preserve(), OPENROUTER_BASE_URL: preserve(), OPENROUTER_MODEL: preserve(), OPENROUTER_REASONING_EFFORT: preserve(), PORT: preserve(), REDIS_URL: preserve(), TEST_DATABASE_URL: preserve() },
  });
  const Postgres = service("Postgres", {
    source: image("postgis/postgis:16-3.4-alpine"),
    build: { buildEnvironment: "V3", builder: "RAILPACK" },
    replicas: { "sfo": 1 },
    networking: { privateNetworkEndpoint: "postgres" },
    volumeMounts: { "/var/lib/postgresql/data": postgresVolume },
    env: { DATABASE_URL: preserve(), PGDATA: preserve(), POSTGRES_DB: preserve(), POSTGRES_PASSWORD: preserve(), POSTGRES_USER: preserve() },
  });

  return project("greensentinel", {
    variables: { managed: true },
    resources: [greensentinelBackend, Postgres, Redis, postgresVolume, redisVolume],
  });
});
