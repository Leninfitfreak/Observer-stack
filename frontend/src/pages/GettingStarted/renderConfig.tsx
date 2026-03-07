import {
	AlertFilled,
	AlignLeftOutlined,
	ApiFilled,
	BarChartOutlined,
	DashboardFilled,
	SoundFilled,
} from '@ant-design/icons';
import { Typography } from 'antd';
import store from 'store';

import { TGetStartedContentSection } from './types';

export const GetStartedContent = (): TGetStartedContentSection[] => {
	const {
		app: { currentVersion },
	} = store.getState();
	return [
		{
			heading: 'Send data from your applications to Observer Stack',
			items: [
				{
					title: 'Instrument your Java Application',
					icon: (
						<img src={`/Logos/java.png?currentVersion=${currentVersion}`} alt="" />
					),
					url: '/support',
				},
				{
					title: 'Instrument your Python Application',
					icon: (
						<img src={`/Logos/python.png?currentVersion=${currentVersion}`} alt="" />
					),
					url: '/support',
				},
				{
					title: 'Instrument your JS Application',
					icon: (
						<img
							src={`/Logos/javascript.png?currentVersion=${currentVersion}`}
							alt=""
						/>
					),
					url: '/support',
				},
				{
					title: 'Instrument your Go Application',
					icon: (
						<img src={`/Logos/go.png?currentVersion=${currentVersion}`} alt="" />
					),
					url: '/support',
				},
				{
					title: 'Instrument your .NET Application',
					icon: (
						<img
							src={`/Logos/ms-net-framework.png?currentVersion=${currentVersion}`}
							alt=""
						/>
					),
					url: '/support',
				},
				{
					title: 'Instrument your PHP Application',
					icon: (
						<img src={`/Logos/php.png?currentVersion=${currentVersion}`} alt="" />
					),
					url: '/support',
				},
				{
					title: 'Instrument your Rails Application',
					icon: (
						<img src={`/Logos/rails.png?currentVersion=${currentVersion}`} alt="" />
					),
					url: '/support',
				},
				{
					title: 'Instrument your Rust Application',
					icon: (
						<img src={`/Logos/rust.png?currentVersion=${currentVersion}`} alt="" />
					),
					url: '/support',
				},
				{
					title: 'Instrument your Elixir Application',
					icon: (
						<img src={`/Logos/elixir.png?currentVersion=${currentVersion}`} alt="" />
					),
					url: '/support',
				},
			],
		},
		{
			heading: 'Send Metrics from your Infrastructure & create Dashboards',
			items: [
				{
					title: 'Send metrics to Observer Stack',
					icon: <BarChartOutlined style={{ fontSize: '3.5rem' }} />,
					url: '/support',
				},
				{
					title: 'Create and Manage Dashboards',
					icon: <DashboardFilled style={{ fontSize: '3.5rem' }} />,
					url: '/support',
				},
			],
		},
		{
			heading: 'Send your logs to Observer Stack',
			items: [
				{
					title: 'Send your logs to Observer Stack',
					icon: <AlignLeftOutlined style={{ fontSize: '3.5rem' }} />,
					url: '/support',
				},
				{
					title: 'Existing log collectors to Observer Stack',
					icon: <ApiFilled style={{ fontSize: '3.5rem' }} />,
					url: '/support',
				},
			],
		},
		{
			heading: 'Create alerts on Metrics',
			items: [
				{
					title: 'Create alert rules on metrics',
					icon: <AlertFilled style={{ fontSize: '3.5rem' }} />,
					url: '/support',
				},
				{
					title: 'Configure alert notification channels',
					icon: <SoundFilled style={{ fontSize: '3.5rem' }} />,
					url: '/support',
				},
			],
		},
		{
			heading: 'Need help?',
			description: <>Use the built-in support workflow inside Observer Stack.</>,

			items: [
				{
					title: 'Open Support',
					icon: <Typography.Text strong>OS</Typography.Text>,
					url: '/support',
				},
			],
		},
	];
};
