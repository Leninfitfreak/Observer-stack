import history from 'lib/history';

import './FullScreenHeader.styles.scss';

export default function FullScreenHeader({
	overrideRoute,
}: {
	overrideRoute?: string;
}): React.ReactElement {
	const handleLogoClick = (): void => {
		history.push(overrideRoute || '/');
	};
	return (
		<div className="full-screen-header-container">
			<div className="brand-logo" onClick={handleLogoClick}>
				<div className="brand-logo-name">Observer Stack</div>
			</div>
		</div>
	);
}

FullScreenHeader.defaultProps = {
	overrideRoute: '/',
};
