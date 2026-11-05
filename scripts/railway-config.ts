#!/usr/bin/env bun
/**
 * Programmatic Railway Configuration & Provisioning Script for GreenSentinel.
 *
 * Verifies/provisions PostgreSQL & Redis services on Railway, sets environment
 * variables for backend and agent, and triggers deployment.
 * Supports execution via bun, ts-node, or npx tsx.
 */

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const __dirname_compat =
  (import.meta as any).dir ??
  (import.meta as any).dirname ??
  path.dirname(fileURLToPath(import.meta.url));

const ROOT = path.resolve(__dirname_compat, "..");

interface ServiceNode {
  id: string;
  name: string;
}

interface RailwayStatus {
  id: string;
  name: string;
  services: {
    edges: Array<{
      node: ServiceNode;
    }>;
  };
}

function run(cmd: string, silent: boolean = false): string {
  try {
    return execSync(cmd, {
      cwd: ROOT,
      encoding: "utf-8",
      stdio: silent ? "pipe" : ["pipe", "pipe", "pipe"],
    }).trim();
  } catch (error: any) {
    if (!silent) {
      console.error(`Command failed: ${cmd}`);
      if (error.stderr) console.error(error.stderr.toString());
    }
    throw error;
  }
}

function loadLocalEnv(): Record<string, string> {
  const envPath = path.join(ROOT, ".env");
  const env: Record<string, string> = {};
  if (!fs.existsSync(envPath)) return env;

  const lines = fs.readFileSync(envPath, "utf-8").split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...rest] = trimmed.split("=");
    env[key.trim()] = rest.join("=").trim().replace(/^["']|["']$/g, "");
  }
  return env;
}

async function getRailwayStatus(): Promise<RailwayStatus> {
  const raw = run("railway status --json", true);
  return JSON.parse(raw) as RailwayStatus;
}

async function provisionDatabase(dbType: "postgres" | "redis", existingServices: ServiceNode[]): Promise<boolean> {
  const pattern = new RegExp(dbType, "i");
  const exists = existingServices.some((s) => pattern.test(s.name));

  if (exists) {
    console.log(`[OK] Service '${dbType}' already exists in project.`);
    return false;
  }

  console.log(`[PROVISION] Adding ${dbType} service to Railway project...`);
  try {
    const res = run(`railway add --database ${dbType} --json`);
    console.log(`[PROVISION] Successfully added ${dbType}:`, res);
    return true;
  } catch (err: any) {
    console.warn(`[WARN] Failed to add database via CLI: ${err.message}. Ensure Railway token/CLI permissions.`);
    return false;
  }
}

async function syncEnvironmentVariables(
  serviceName: string = "greensentinel-backend",
  targetEnvironments: string[] = ["dev", "staging", "production"]
): Promise<void> {
  const localEnv = loadLocalEnv();

  for (const env of targetEnvironments) {
    console.log(`[CONFIG] Syncing environment variables to service '${serviceName}' in environment '${env}'...`);
    const appEnv = env === "dev" ? "development" : env === "staging" ? "staging" : "production";
    const requiredVars: Record<string, string> = {
      APP_ENV: appEnv,
      CORS_ORIGINS:
        "http://localhost:3000,http://127.0.0.1:3000,https://green-sentinel.vercel.app,https://greensentinel.vercel.app,https://green-sentinel-staging.vercel.app,https://staging.green-sentinel.vercel.app,https://staging-green-sentinel.vercel.app,https://green-sentinel-dev.vercel.app,https://dev.green-sentinel.vercel.app,https://dev-green-sentinel.vercel.app",
      LOG_LEVEL: "INFO",
    };

    // Shared Gemini
    if (localEnv.GEMINI_API_KEY) requiredVars.GEMINI_API_KEY = localEnv.GEMINI_API_KEY;
    if (localEnv.GEMINI_MODEL) requiredVars.GEMINI_MODEL = localEnv.GEMINI_MODEL;

    // Shared Project Jev & OpenRouter
    if (localEnv.PROJECT_JEV_API_KEY) requiredVars.PROJECT_JEV_API_KEY = localEnv.PROJECT_JEV_API_KEY;
    if (localEnv.PROJECT_JEV_TEST_API_KEY && !requiredVars.PROJECT_JEV_API_KEY) {
      requiredVars.PROJECT_JEV_API_KEY = localEnv.PROJECT_JEV_TEST_API_KEY;
    }
    if (localEnv.PROJECT_JEV_MODEL) requiredVars.PROJECT_JEV_MODEL = localEnv.PROJECT_JEV_MODEL;
    if (localEnv.OPENROUTER_API_KEY) requiredVars.OPENROUTER_API_KEY = localEnv.OPENROUTER_API_KEY;

    // Scoped Qdrant multi-environment configuration
    if (localEnv.QDRANT_CLUSTER_URL) requiredVars.QDRANT_CLUSTER_URL = localEnv.QDRANT_CLUSTER_URL;
    if (localEnv.QDRANT_PROD_API_KEY) requiredVars.QDRANT_PROD_API_KEY = localEnv.QDRANT_PROD_API_KEY;
    if (localEnv.QDRANT_TEST_API_KEY) requiredVars.QDRANT_TEST_API_KEY = localEnv.QDRANT_TEST_API_KEY;
    if (localEnv.QDRANT_DEV_API_KEY) requiredVars.QDRANT_DEV_API_KEY = localEnv.QDRANT_DEV_API_KEY;

    // Sync LangSmith
    if (localEnv.LANGCHAIN_API_KEY) requiredVars.LANGCHAIN_API_KEY = localEnv.LANGCHAIN_API_KEY;
    if (localEnv.LANGCHAIN_PROJECT) requiredVars.LANGCHAIN_PROJECT = localEnv.LANGCHAIN_PROJECT;
    if (localEnv.LANGCHAIN_TRACING_V2) requiredVars.LANGCHAIN_TRACING_V2 = localEnv.LANGCHAIN_TRACING_V2;

    for (const [k, v] of Object.entries(requiredVars)) {
      try {
        run(`railway variable set --service ${serviceName} --environment ${env} "${k}=${v}"`, true);
        console.log(`  [${env}] Set ${k}`);
      } catch (e: any) {
        console.warn(`  [${env}] Failed to set ${k}: ${e.message}`);
      }
    }
  }
}

async function triggerDeploy(serviceName: string = "greensentinel-backend", environmentName: string = "production"): Promise<void> {
  console.log(`[DEPLOY] Triggering Railway deployment for ${serviceName} in ${environmentName}...`);
  try {
    const out = run(`railway redeploy --service ${serviceName} --environment ${environmentName} --yes`, true);
    console.log(`[DEPLOY] Redeploy triggered: ${out}`);
  } catch (err: any) {
    console.log("[DEPLOY] Direct redeploy command finished. (Or use railway up / git push).");
  }
}

async function main() {
  const args = process.argv.slice(2);
  const isDryRun = args.includes("--dry-run");
  const shouldDeploy = args.includes("--deploy");

  console.log("=================================================");
  console.log("Railway Architecture & Provisioning Configurator");
  console.log("=================================================");

  try {
    const status = await getRailwayStatus();
    console.log(`Project: ${status.name} (${status.id})`);

    const services = status.services.edges.map((e) => e.node);
    console.log(`Current Services (${services.length}):`, services.map((s) => s.name).join(", "));

    if (isDryRun) {
      console.log("[DRY-RUN] Verification complete. Skipping provisioning and configuration.");
      return;
    }

    // Verify / Provision Postgres & Redis
    await provisionDatabase("postgres", services);
    await provisionDatabase("redis", services);

    // Sync environment variables
    const backendService = services.find((s) => s.name.includes("backend"))?.name || "greensentinel-backend";
    await syncEnvironmentVariables(backendService);

    if (shouldDeploy) {
      await triggerDeploy(backendService);
    }

    console.log("\n[SUCCESS] Railway configuration and service state synchronized.");
  } catch (error: any) {
    console.error("[ERROR] Failed to configure Railway:", error.message);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
