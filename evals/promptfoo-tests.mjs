import fs from "node:fs";

const casesPath = new URL("./cases.json", import.meta.url);
const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));

function toPromptfooTest(testCase) {
  const assertions = [];
  const expectedTools = testCase.expected?.tools ?? [];
  const expectedArgs = testCase.expected?.args ?? {};

  if (expectedTools.length > 0) {
    assertions.push({
      type: "javascript",
      metric: "tool_routing",
      value: "file://assertions/tool-args.cjs:assertToolsPresent",
      config: {
        expectedTools,
      },
    });
  }

  if (Object.keys(expectedArgs).length > 0) {
    assertions.push({
      type: "javascript",
      metric: "tool_args",
      value: "file://assertions/tool-args.cjs:assertToolArgs",
      config: {
        expectedArgs,
      },
    });
  }

  return {
    description: testCase.description,
    vars: {
      prompt: testCase.prompt,
    },
    metadata: {
      case_id: testCase.id,
      tags: testCase.tags ?? [],
    },
    assert: assertions,
  };
}

export default cases
  .filter((testCase) => Array.isArray(testCase.suites) && testCase.suites.includes("promptfoo"))
  .map(toPromptfooTest);
