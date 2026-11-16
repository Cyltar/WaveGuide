import Icon from "@/components/Icon";

export default function LoadingScreen() {
  return (
    <main className="auth-page">
      <div className="loading-brand" role="status">
        <Icon name="wave" className="brand-mark" />
        <span>Loading WaveGuide</span>
      </div>
    </main>
  );
}
