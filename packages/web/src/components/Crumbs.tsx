import Link from "next/link";

/** Breadcrumb trail; the last item is the current page. */
export function Crumbs({ items }: { items: { href?: string; label: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="meta flex flex-wrap items-center gap-1.5">
      {items.map((it, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span aria-hidden>/</span>}
          {it.href ? (
            <Link href={it.href} className="link">
              {it.label}
            </Link>
          ) : (
            <span className="text-fg">{it.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
