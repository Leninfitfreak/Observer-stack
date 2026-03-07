import { useCallback, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Button, Popover } from 'antd';
import logEvent from 'api/common/logEvent';
import { useGetTenantLicense } from 'hooks/useGetTenantLicense';
import { Inbox, SquarePen } from 'lucide-react';

import AnnouncementsModal from './AnnouncementsModal';
import FeedbackModal from './FeedbackModal';

import './HeaderRightSection.styles.scss';

interface HeaderRightSectionProps {
	enableAnnouncements: boolean;
	enableShare: boolean;
	enableFeedback: boolean;
}

function HeaderRightSection({
	enableAnnouncements,
	enableShare,
	enableFeedback,
}: HeaderRightSectionProps): JSX.Element | null {
	const location = useLocation();

	const [openFeedbackModal, setOpenFeedbackModal] = useState(false);
	const [openAnnouncementsModal, setOpenAnnouncementsModal] = useState(false);

	const { isCloudUser, isEnterpriseSelfHostedUser } = useGetTenantLicense();

	const handleOpenFeedbackModal = useCallback((): void => {
		logEvent('Feedback: Clicked', {
			page: location.pathname,
		});

		setOpenFeedbackModal(true);
		setOpenAnnouncementsModal(false);
	}, [location.pathname]);

	const handleCloseFeedbackModal = (): void => {
		setOpenFeedbackModal(false);
	};

	const handleOpenFeedbackModalChange = (open: boolean): void => {
		setOpenFeedbackModal(open);
	};

	const handleOpenAnnouncementsModalChange = (open: boolean): void => {
		setOpenAnnouncementsModal(open);
	};

	const isLicenseEnabled = isEnterpriseSelfHostedUser || isCloudUser;

	return (
		<div className="header-right-section-container">
			{enableFeedback && isLicenseEnabled && (
				<Popover
					rootClassName="header-section-popover-root"
					className="shareable-link-popover"
					placement="bottomRight"
					content={<FeedbackModal onClose={handleCloseFeedbackModal} />}
					destroyTooltipOnHide
					arrow={false}
					trigger="click"
					open={openFeedbackModal}
					onOpenChange={handleOpenFeedbackModalChange}
				>
					<Button
						className="share-feedback-btn periscope-btn ghost"
						icon={<SquarePen size={14} />}
						onClick={handleOpenFeedbackModal}
					>
						Feedback
					</Button>
				</Popover>
			)}

			{enableAnnouncements && (
				<Popover
					rootClassName="header-section-popover-root"
					className="shareable-link-popover"
					placement="bottomRight"
					content={<AnnouncementsModal />}
					arrow={false}
					destroyTooltipOnHide
					trigger="click"
					open={openAnnouncementsModal}
					onOpenChange={handleOpenAnnouncementsModalChange}
				>
					<Button
						icon={<Inbox size={14} />}
						className="periscope-btn ghost announcements-btn"
						onClick={(): void => {
							logEvent('Announcements: Clicked', {
								page: location.pathname,
							});
						}}
					/>
				</Popover>
			)}

			{enableShare && null}
		</div>
	);
}

export default HeaderRightSection;
