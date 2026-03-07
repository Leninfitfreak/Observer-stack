import { useEffect, useState } from 'react';
import { useMutation } from 'react-query';
import { useHistory, useLocation } from 'react-router-dom';
import { Button, Card, Modal, Typography } from 'antd';
import logEvent from 'api/common/logEvent';
import updateCreditCardApi from 'api/v1/checkout/create';
import { FeatureKeys } from 'constants/features';
import { useNotifications } from 'hooks/useNotifications';
import {
	ArrowUpRight,
	CreditCard,
	LifeBuoy,
	MessageSquare,
	X,
} from 'lucide-react';
import { useAppContext } from 'providers/App/App';
import { SuccessResponseV2 } from 'types/api';
import { CheckoutSuccessPayloadProps } from 'types/api/billing/checkout';
import APIError from 'types/api/error';

import './Support.styles.scss';

const { Title, Text } = Typography;

interface Channel {
	key: any;
	name?: string;
	icon?: JSX.Element;
	title?: string;
	url: any;
	btnText?: string;
}

const channelsMap = {
	documentation: 'documentation',
	github: 'github',
	slack_community: 'slack_community',
	chat: 'chat',
	schedule_call: 'schedule_call',
	slack_connect: 'slack_connect',
};

const supportChannels = [
	{
		key: 'chat',
		name: 'Support',
		icon: <MessageSquare size={16} />,
		title: 'Use the in-product support workflow available in this workspace.',
		url: '',
		btnText: 'Open support',
		isExternal: false,
	},
];

export default function Support(): JSX.Element {
	const history = useHistory();
	const { notifications } = useNotifications();
	const { trialInfo, featureFlags } = useAppContext();
	const [isAddCreditCardModalOpen, setIsAddCreditCardModalOpen] = useState(
		false,
	);

	const { pathname } = useLocation();

	useEffect(() => {
		if (history?.location?.state) {
			const histroyState = history?.location?.state as any;

			if (histroyState && histroyState?.from) {
				logEvent(`Support : From URL : ${histroyState.from}`, {});
			}
		}

		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const isPremiumChatSupportEnabled =
		featureFlags?.find((flag) => flag.name === FeatureKeys.PREMIUM_SUPPORT)
			?.active || false;

	const showAddCreditCardModal =
		!isPremiumChatSupportEnabled && !trialInfo?.trialConvertedToSubscription;

	const handleBillingOnSuccess = (
		data: SuccessResponseV2<CheckoutSuccessPayloadProps>,
	): void => {
		if (data?.data?.redirectURL) {
			const newTab = document.createElement('a');
			newTab.href = data.data.redirectURL;
			newTab.target = '_blank';
			newTab.rel = 'noopener noreferrer';
			newTab.click();
		}
	};

	const handleBillingOnError = (error: APIError): void => {
		notifications.error({
			message: error.getErrorCode(),
			description: error.getErrorMessage(),
		});
	};

	const { mutate: updateCreditCard, isLoading: isLoadingBilling } = useMutation(
		updateCreditCardApi,
		{
			onSuccess: (data) => {
				handleBillingOnSuccess(data);
			},
			onError: handleBillingOnError,
		},
	);

	const handleAddCreditCard = (): void => {
		logEvent('Add Credit card modal: Clicked', {
			source: `help & support`,
			page: pathname,
		});

		updateCreditCard({
			url: window.location.origin,
		});
	};

	const handleChat = (): void => {
		if (showAddCreditCardModal) {
			logEvent('Disabled Chat Support: Clicked', {
				source: `help & support`,
				page: pathname,
			});
			setIsAddCreditCardModalOpen(true);
		} else if (window.pylon) {
			window.Pylon('show');
		}
	};

	const handleChannelClick = (channel: Channel): void => {
		logEvent(`Support : ${channel.name}`, {});

		switch (channel.key) {
			case channelsMap.chat:
				handleChat();
				break;
			default:
				history.push('/');
				break;
		}
	};

	return (
		<div className="support-page-container">
			<header className="support-page-header">
				<div className="support-page-header-title" data-testid="support-page-title">
					<LifeBuoy size={16} />
					Support
				</div>
			</header>

			<div className="support-page-content">
				<div className="support-page-content-description">
					Observer Stack support is handled inside the product interface. External
					community and marketing links have been removed from this workspace.
				</div>

				<div className="support-channels">
					{supportChannels.map(
						(channel): JSX.Element => (
							<Card className="support-channel" key={channel.key}>
								<div className="support-channel-content">
									<Title ellipsis level={5} className="support-channel-title">
										{channel.icon}
										{channel.name}{' '}
									</Title>
									<Text> {channel.title} </Text>
								</div>

								<div className="support-channel-action">
									<Button
										className="periscope-btn secondary support-channel-btn"
										type="default"
										onClick={(): void => handleChannelClick(channel)}
									>
										<Text ellipsis>{channel.btnText} </Text>
										{channel.isExternal && <ArrowUpRight size={14} />}
									</Button>
								</div>
							</Card>
						),
					)}
				</div>
			</div>

			{/* Add Credit Card Modal */}
			<Modal
				className="add-credit-card-modal"
				title={<span className="title">Add Credit Card for Chat Support</span>}
				open={isAddCreditCardModalOpen}
				closable
				onCancel={(): void => setIsAddCreditCardModalOpen(false)}
				destroyOnClose
				footer={[
					<Button
						key="cancel"
						onClick={(): void => setIsAddCreditCardModalOpen(false)}
						className="cancel-btn"
						icon={<X size={16} />}
					>
						Cancel
					</Button>,
					<Button
						key="submit"
						type="primary"
						icon={<CreditCard size={16} />}
						size="middle"
						loading={isLoadingBilling}
						disabled={isLoadingBilling}
						onClick={handleAddCreditCard}
						className="add-credit-card-btn periscope-btn primary"
					>
						Add Credit Card
					</Button>,
				]}
			>
				<Typography.Text className="add-credit-card-text">
					You&apos;re currently on <span className="highlight-text">Trial plan</span>
					. Add a credit card to access Observer Stack chat support in your workspace.
				</Typography.Text>
			</Modal>
		</div>
	);
}
