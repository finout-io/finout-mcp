function collectToolInputs(output, toolInputs = {}) {
  if (output === null || output === undefined) {
    return toolInputs;
  }

  if (typeof output === "string") {
    try {
      return collectToolInputs(JSON.parse(output), toolInputs);
    } catch {
      const lines = output.split("\n");
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || (!trimmed.startsWith("{") && !trimmed.startsWith("["))) {
          continue;
        }
        try {
          collectToolInputs(JSON.parse(trimmed), toolInputs);
        } catch {
          // Ignore non-JSON lines in mixed model output.
        }
      }
      return toolInputs;
    }
  }

  if (Array.isArray(output)) {
    for (const item of output) {
      collectToolInputs(item, toolInputs);
    }
    return toolInputs;
  }

  if (typeof output !== "object") {
    return toolInputs;
  }

  if (Array.isArray(output.tool_calls)) {
    for (const toolCall of output.tool_calls) {
      if (!toolCall || typeof toolCall !== "object") {
        continue;
      }
      if (toolCall.function && typeof toolCall.function === "object") {
        const name = toolCall.function.name;
        let args = toolCall.function.arguments;
        if (typeof args === "string") {
          try {
            args = JSON.parse(args);
          } catch {
            // Keep string value for mismatch reporting.
          }
        }
        if (typeof name === "string") {
          toolInputs[name] = args;
        }
      } else if (typeof toolCall.name === "string") {
        toolInputs[toolCall.name] = toolCall.input;
      }
    }
  }

  if (output.type === "tool_use" && typeof output.name === "string") {
    toolInputs[output.name] = output.input;
  }

  return toolInputs;
}

function hasPresentOperator(expected) {
  return (
    expected &&
    typeof expected === "object" &&
    !Array.isArray(expected) &&
    expected.$present === true
  );
}

function hasRegexOperator(expected) {
  return (
    expected &&
    typeof expected === "object" &&
    !Array.isArray(expected) &&
    typeof expected.$regex === "string"
  );
}

function dictContains(actual, expected) {
  if (!actual || typeof actual !== "object") {
    return false;
  }

  return Object.entries(expected).every(([key, value]) => {
    if (hasPresentOperator(value)) {
      return actual[key] !== undefined && actual[key] !== null;
    }

    if (hasRegexOperator(value)) {
      return (
        typeof actual[key] === "string" &&
        new RegExp(value.$regex).test(actual[key])
      );
    }

    if (Array.isArray(value)) {
      return matchValue(actual[key], value).ok;
    }

    if (value && typeof value === "object") {
      return dictContains(actual[key], value);
    }

    return actual[key] === value;
  });
}

function matchValue(actual, expected) {
  if (expected === null) {
    return actual === undefined || actual === null
      ? { ok: true }
      : { ok: false, reason: `should be absent, got ${JSON.stringify(actual)}` };
  }

  if (hasPresentOperator(expected) || (expected && typeof expected === "object" && !Array.isArray(expected) && Object.keys(expected).length === 0)) {
    return actual !== undefined && actual !== null
      ? { ok: true }
      : { ok: false, reason: "missing" };
  }

  if (hasRegexOperator(expected)) {
    return typeof actual === "string" && new RegExp(expected.$regex).test(actual)
      ? { ok: true }
      : {
          ok: false,
          reason: `value ${JSON.stringify(actual)} does not match /${expected.$regex}/`,
        };
  }

  if (Array.isArray(expected)) {
    const actualList = Array.isArray(actual) ? actual : [];
    for (const expectedItem of expected) {
      if (expectedItem && typeof expectedItem === "object" && !Array.isArray(expectedItem)) {
        const found = actualList.some((actualItem) => dictContains(actualItem, expectedItem));
        if (!found) {
          return {
            ok: false,
            reason: `missing item ${JSON.stringify(expectedItem)}`,
          };
        }
        continue;
      }

      if (!actualList.includes(expectedItem)) {
        return {
          ok: false,
          reason: `missing value ${JSON.stringify(expectedItem)}`,
        };
      }
    }

    return { ok: true };
  }

  if (expected && typeof expected === "object") {
    if (!actual || typeof actual !== "object") {
      return {
        ok: false,
        reason: `expected object ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
      };
    }

    for (const [key, nestedExpected] of Object.entries(expected)) {
      const nested = matchValue(actual[key], nestedExpected);
      if (!nested.ok) {
        return {
          ok: false,
          reason: `${key} ${nested.reason}`,
        };
      }
    }

    return { ok: true };
  }

  return actual === expected
    ? { ok: true }
    : {
        ok: false,
        reason: `${JSON.stringify(actual)} != ${JSON.stringify(expected)}`,
      };
}

function assertToolArgs(output, context) {
  const expectedArgs = context?.config?.expectedArgs ?? {};
  const toolInputs = collectToolInputs(output, {});
  const mismatches = [];

  for (const [toolName, expected] of Object.entries(expectedArgs)) {
    const actual = toolInputs[toolName];
    if (actual === undefined) {
      mismatches.push(`${toolName} not called`);
      continue;
    }

    for (const [param, expectedValue] of Object.entries(expected)) {
      const result = matchValue(actual?.[param], expectedValue);
      if (!result.ok) {
        mismatches.push(`${toolName}.${param} ${result.reason}`);
      }
    }
  }

  if (mismatches.length > 0) {
    return {
      pass: false,
      score: 0,
      reason: mismatches.join("; "),
    };
  }

  return {
    pass: true,
    score: 1,
    reason: "All args match",
  };
}

function assertToolsPresent(output, context) {
  const expectedTools = context?.config?.expectedTools ?? [];
  const toolInputs = collectToolInputs(output, {});
  const actualTools = new Set(Object.keys(toolInputs));
  const missing = expectedTools.filter((toolName) => !actualTools.has(toolName));

  if (missing.length > 0) {
    return {
      pass: false,
      score: 0,
      reason: `Missing expected tools: ${missing.join(", ")}`,
    };
  }

  return {
    pass: true,
    score: 1,
    reason: "All expected tools were called",
  };
}

module.exports = {
  assertToolsPresent,
  assertToolArgs,
};
