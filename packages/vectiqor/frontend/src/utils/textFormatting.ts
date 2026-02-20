export function formatReadableText(input: string): string {
  if (!input) return input

  const normalized = input.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

  // Avoid rewriting structured/code output.
  if (normalized.includes('```')) return normalized

  const lines = normalized.split('\n')
  const formatted = lines.map((line) => {
    const trimmed = line.trim()
    if (!trimmed) return line

    // Keep existing list/table-like lines intact.
    if (/^[-*]\s/.test(trimmed) || /^\d+\.\s/.test(trimmed) || trimmed.includes('|')) {
      return line
    }

    return line
      // Break after sentence endings when followed by a new sentence token.
      // Handles both "end. Next" and chunk-joined "end.Next".
      .replace(/([.?!])[ \t]*(?=[A-Z0-9])/g, '$1\n')
      // Break after colon before a clause/list (with or without spaces).
      .replace(/(:)[ \t]*(?=[A-Z0-9])/g, '$1\n')
  })

  return formatted.join('\n')
}
