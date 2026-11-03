// Saves the GitHub repo and digit color for the stars feature and hands them to the Python service.
export default defineEventHandler(async (event) => {
  const { repo, color } = await readBody<{ repo?: unknown; color?: unknown }>(event)
  if (typeof repo !== 'string' || !REPO_PATTERN.test(repo.trim())) throw createError({ statusCode: 400, data: { error: 'repo must look like owner/name' } })
  if (color !== undefined && (typeof color !== 'string' || !COLOR_PATTERN.test(color)))
    throw createError({ statusCode: 400, data: { error: 'color must be a 6-digit hex value' } })
  const result = await pushStars({ repo: repo.trim(), color: color?.replace('#', '') })
  await saveStars({ repo: result.repo, color: result.color })
  return result
})
