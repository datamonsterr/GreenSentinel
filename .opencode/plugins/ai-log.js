import { spawn } from "node:child_process";

export const AiLogPlugin = async (ctx) => {
  const projectDir = ctx?.directory || process.cwd();
  return {
    "chat.message": async (input, output) => {
      try {
        const text = output?.parts
          ?.filter(p => p && p.type === "text")
          .map(p => p.text)
          .join("\n") || "";
        if (!text) return;

        const payload = JSON.stringify({
          hook_event_name: "chat.message",
          sessionID: input.sessionID,
          prompt: text,
          model: input.model?.modelID || ""
        });

        const proc = spawn("bash", ["scripts/_pyrun.sh", "scripts/log_hook.py", "--tool=opencode"], {
          cwd: projectDir,
          stdio: ["pipe", "ignore", "ignore"]
        });
        proc.stdin.write(payload);
        proc.stdin.end();
      } catch (err) {
        // Never block or crash host editor
      }
    }
  };
};

export default AiLogPlugin;
