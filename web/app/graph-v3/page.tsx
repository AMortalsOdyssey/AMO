import GraphV3View from "@/components/graph-v3/GraphV3View";

export default async function GraphV3Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  return <GraphV3View initialSearchParams={params} />;
}
