import { redirect } from "next/navigation";

export default async function GraphV2Redirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const next = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (typeof value === "string") {
      next.set(key, value);
      return;
    }
    value?.forEach((item) => next.append(key, item));
  });

  const query = next.toString();
  redirect(`/graph-v3${query ? `?${query}` : ""}`);
}
