import React from 'react';
import './AuthFooter.styles.scss';

interface FooterItem {
	icon?: string;
	text: string;
	url?: string;
	statusIndicator?: boolean;
}

const footerItems: FooterItem[] = [
	{
		text: 'All systems operational',
		statusIndicator: true,
	},
	{
		text: 'Privacy',
	},
	{
		text: 'Security',
	},
];

function AuthFooter(): JSX.Element {
	return (
		<footer className="auth-footer">
			<div className="auth-footer-content">
				{footerItems.map((item, index) => (
					<React.Fragment key={item.text}>
						<div className="auth-footer-item">
							{item.statusIndicator && (
								<div className="auth-footer-status-indicator" />
							)}
							{item.icon && (
								<img
									loading="lazy"
									src={item.icon}
									alt=""
									className="auth-footer-icon"
								/>
							)}
							<span className="auth-footer-text">{item.text}</span>
						</div>
						{index < footerItems.length - 1 && (
							<div className="auth-footer-separator" />
						)}
					</React.Fragment>
				))}
			</div>
		</footer>
	);
}

export default AuthFooter;
