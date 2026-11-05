import fs from "node:fs";
import path from "node:path";
import { z } from "zod";
import { resolveJevModule, DEFAULT_SKILLS_BANK } from "../../scripts/jev_hook";

const defaultSkillsDir =
  process.env.SKILLS_BANK_PATH || DEFAULT_SKILLS_BANK;

function formatPluginRouting(prompt: string, skills: any[]): string {
  if (skills.length === 0) return "";
  const lines = [
    "🎯 **[Jev Dynamic Skill Routing]**",
    `User Request: "${prompt}"`,
    "",
    "Recommended skill(s) for this task:",
    "",
  ];
  for (const skill of skills) {
    const prob = (skill.probability * 100).toFixed(1);
    const conf = (skill.confidence * 100).toFixed(0);
    const skillFile = path.join(defaultSkillsDir, skill.name, "SKILL.md");
    lines.push(`• **${skill.name}** (Prob: ${prob}% | Conf: ${conf}%)`);
    if (fs.existsSync(skillFile)) {
      lines.push(`  - Path: \`${skillFile}\``);
    }
    if (skill.description) {
      lines.push(`  - Description: ${skill.description}`);
    }
  }
  lines.push("");
  lines.push("*Instruction:* Read and follow the recommended skill workflow if relevant to the request.");
  return lines.join("\n");
}

export default async function jevSkillSelectorPlugin() {
  const jev = await resolveJevModule();
  const selectSkills = jev.selectSkills;
  return {
    name: "jev-skill-selector",
    version: "1.1.0",
    description: "Jev dynamic skill router and RTK/Headroom post-tool optimization for P-063",
    hooks: {
      "experimental.chat.messages.transform": async (_input: unknown, output: any) => {
        if (!Array.isArray(output?.messages)) return;
        const lastUser = [...output.messages]
          .reverse()
          .find((entry: any) => entry?.info?.role === "user");
        const prompt = (lastUser?.parts ?? [])
          .filter((part: any) => part?.type === "text" && typeof part.text === "string")
          .map((part: any) => part.text)
          .join("\n")
          .trim();
        if (!prompt) return;

        try {
          const result = await selectSkills({
            userPrompt: prompt,
            skillsDir: defaultSkillsDir,
            options: { threshold: 0.05, maxSkills: 3 },
          });
          if (result.selectedSkills.length > 0) {
            output.messages.push({
              info: { role: "system", synthetic: true },
              parts: [{ type: "text", text: formatPluginRouting(prompt, result.selectedSkills) }],
            });
          }
        } catch (error: any) {
          console.warn(`[jev-skill-selector] ${error.message}`);
        }
      },
      "tool.execute.after": async (
        input: { tool: string; sessionID: string; callID: string; args: any },
        output: { title: string; output: string; metadata: any }
      ) => {
        // Headroom buffer protection: truncate large tool outputs to conserve context
        if (typeof output.output === "string" && output.output.length > 3500) {
          const lines = output.output.split("\n");
          if (lines.length > 80) {
            const head = lines.slice(0, 40).join("\n");
            const tail = lines.slice(-20).join("\n");
            output.output = `${head}\n\n... [Headroom: ${lines.length - 60} lines truncated to conserve context headroom] ...\n\n${tail}`;
          }
        }
      },
    },
    tools: [
      {
        name: "select_skill",
        description: "Select relevant skills from the P-063 private Jev bank",
        parameters: z.object({ task: z.string(), threshold: z.number().optional() }),
        execute: async ({ task, threshold }: { task: string; threshold?: number }) => {
          const result = await selectSkills({
            userPrompt: task,
            skillsDir: defaultSkillsDir,
            options: { threshold: threshold ?? 0.05, maxSkills: 3 },
          });
          return {
            userPrompt: task,
            primarySkill: result.primarySkill,
            skills: result.selectedSkills,
            summary: formatPluginRouting(task, result.selectedSkills),
          };
        },
      },
    ],
  };
}
