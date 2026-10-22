import Link from "next/link";
import { api, unwrap } from "@/lib/api/server";
import { formatDate } from "@/lib/format";

export default async function Projects() {
  const client = await api();
  const projects = unwrap(await client.GET("/v1/projects"));
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 px-4 py-5 sm:px-5">
      <h1 className="text-[17px] font-semibold">Projects</h1>
      <section className="pane overflow-x-auto">
        {projects.length === 0 ? (
          <p className="p-4 text-muted">
            No projects yet. Create one with <code className="font-mono">POST /v1/projects</code>.
          </p>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Name</th>
                <th>Created</th>
                <th>Id</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link href={`/projects/${p.id}`} className="link">
                      {p.name}
                    </Link>
                  </td>
                  <td>{formatDate(p.created_at)}</td>
                  <td className="text-muted">{p.id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
