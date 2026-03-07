import { useCallback } from 'react';
import { Button } from '@signozhq/button';
import { LifeBuoy } from 'lucide-react';

import './AuthHeader.styles.scss';

function AuthHeader(): JSX.Element {
	const handleGetHelp = useCallback((): void => {
		window.location.assign('/support');
	}, []);

	return (
		<header className="auth-header">
			<div className="auth-header-logo">
				<span className="auth-header-logo-text">Observer Stack</span>
			</div>
			<Button
				className="auth-header-help-button"
				prefixIcon={<LifeBuoy size={12} />}
				onClick={handleGetHelp}
			>
				Get Help
			</Button>
		</header>
	);
}

export default AuthHeader;
