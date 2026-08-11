export function Placeholder({ title }: { title: string }) {
  return (
    <div className="p-6">
      <h1 className="font-display text-3xl font-semibold tracking-tight">
        {title}
      </h1>
      <p className="mt-2 text-sm text-text-muted">Not built yet.</p>
    </div>
  );
}
