import { Button, Typography } from 'antd';
import ROUTES from 'constants/routes';
import { ExternalLink, Sparkles } from 'lucide-react';

const { Paragraph, Text, Title } = Typography;

const DEFAULT_EMBED_URL = 'http://localhost:3000';

function DeepObserver(): JSX.Element {
	const observerUrl = DEFAULT_EMBED_URL;

	return (
		<div
			style={{
				display: 'flex',
				flexDirection: 'column',
				height: 'calc(100vh - 72px)',
				padding: '16px 20px 20px',
				gap: 16,
			}}
		>
			<div
				style={{
					display: 'flex',
					justifyContent: 'space-between',
					alignItems: 'flex-start',
					gap: 16,
					flexWrap: 'wrap',
				}}
			>
				<div>
					<Title level={3} style={{ marginBottom: 8 }}>
						<Sparkles size={18} style={{ marginRight: 8 }} />
						Deep Observer AI
					</Title>
					<Paragraph style={{ marginBottom: 0, maxWidth: 880 }}>
						Deep Observer runs as the AI analysis layer on top of the same
						telemetry backend used by Observer Stack. Use it for incident
						correlation, root cause analysis, and remediation guidance without
						switching platforms.
					</Paragraph>
				</div>
				<Button
					href={observerUrl}
					icon={<ExternalLink size={14} />}
					target="_blank"
					rel="noreferrer"
					type="default"
				>
					Open standalone AI view
				</Button>
			</div>
			<div
				style={{
					background: 'var(--bg-ink-400, #111827)',
					border: '1px solid var(--bg-slate-300, #1f2937)',
					borderRadius: 12,
					flex: 1,
					minHeight: 0,
					overflow: 'hidden',
				}}
			>
				<iframe
					src={observerUrl}
					title="Deep Observer AI"
					style={{ width: '100%', height: '100%', border: 0 }}
				/>
			</div>
			<Text type="secondary">
				Observer Stack route: {ROUTES.DEEP_OBSERVER}
			</Text>
		</div>
	);
}

export default DeepObserver;
